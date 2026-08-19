import { useState, useCallback, useEffect } from 'react';
import {
  StyleSheet, Text, View, Button, Image, ScrollView,
  ActivityIndicator, TouchableOpacity, RefreshControl, SafeAreaView,
} from 'react-native';
import * as ImagePicker from 'expo-image-picker';

// Point this at your dev machine's LAN IP -- Expo on a physical device
// can't reach localhost.
const API_BASE = 'http://192.168.2.12:8000/api';

// ---- screens: 'capture' | 'processing' | 'results' | 'review' | 'library' ----

export default function App() {
  const [screen, setScreen] = useState('capture');
  const [scanResult, setScanResult] = useState(null); // raw /api/scan/ response
  const [reviewQueue, setReviewQueue] = useState([]); // books needing action
  const [autoAdded, setAutoAdded] = useState([]); // band === 'auto' books
  const [scanError, setScanError] = useState(null);
  const [lastImage, setLastImage] = useState(null);

  const runScan = useCallback(async (imageAsset) => {
    setLastImage(imageAsset);
    setScreen('processing');
    setScanError(null);
    try {
      const form = new FormData();
      form.append('image', {
        uri: imageAsset.uri,
        name: imageAsset.fileName || 'shelf.jpg',
        type: imageAsset.mimeType || 'image/jpeg',
      });
      const res = await fetch(`${API_BASE}/scan/`, { method: 'POST', body: form });
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      const data = await res.json();
      setScanResult(data);

      const books = data.books || [];
      const auto = books.filter((b) => b.status === 'ok' && b.band === 'auto');
      const needsReview = books.filter(
        (b) => b.status !== 'ok' || b.band !== 'auto'
      );

      // Auto-confirm the confident matches in the background.
      for (const b of auto) {
        postToLibrary(b.match).catch(() => {});
      }

      setAutoAdded(auto);
      setReviewQueue(needsReview.map((b, i) => ({ ...b, _key: `${i}-${Date.now()}` })));
      setScreen('results');
    } catch (err) {
      setScanError(err.message || 'Network request failed');
      setScreen('results');
    }
  }, []);

  const takePhoto = async () => {
    const permission = await ImagePicker.requestCameraPermissionsAsync();
    if (!permission.granted) return;
    const result = await ImagePicker.launchCameraAsync({ quality: 0.7 });
    if (!result.canceled) runScan(result.assets[0]);
  };

  const pickImage = async () => {
    const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) return;
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      quality: 0.7,
    });
    if (!result.canceled) runScan(result.assets[0]);
  };

  const resolveReviewItem = (key) => {
    setReviewQueue((q) => q.filter((b) => b._key !== key));
  };

  if (screen === 'capture') {
    return (
      <CaptureScreen
        onTakePhoto={takePhoto}
        onPickImage={pickImage}
        onViewLibrary={() => setScreen('library')}
      />
    );
  }

  if (screen === 'processing') {
    return <ProcessingScreen image={lastImage} />;
  }

  if (screen === 'results') {
    return (
      <ResultsScreen
        scanResult={scanResult}
        scanError={scanError}
        autoAdded={autoAdded}
        reviewQueue={reviewQueue}
        onRetry={() => lastImage && runScan(lastImage)}
        onScanAgain={() => setScreen('capture')}
        onReview={() => setScreen('review')}
        onViewLibrary={() => setScreen('library')}
      />
    );
  }

  if (screen === 'review') {
    return (
      <ReviewScreen
        queue={reviewQueue}
        onResolve={resolveReviewItem}
        onDone={() => setScreen('results')}
      />
    );
  }

  if (screen === 'library') {
    return <LibraryScreen onBack={() => setScreen('capture')} />;
  }

  return null;
}

async function postToLibrary({ title, author, score }) {
  return fetch(`${API_BASE}/library/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title, author: author || '', match_score: score }),
  });
}

function CaptureScreen({ onTakePhoto, onPickImage, onViewLibrary }) {
  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.centered}>
        <Text style={styles.title}>Shelfie</Text>
        <Text style={styles.subtitle}>Scan a bookshelf to build your library</Text>
        <View style={styles.buttonGroup}>
          <Button title="Take Photo" onPress={onTakePhoto} />
          <Button title="Choose from Library" onPress={onPickImage} />
        </View>
        <TouchableOpacity onPress={onViewLibrary} style={styles.linkButton}>
          <Text style={styles.link}>My Library</Text>
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  );
}

function ProcessingScreen({ image }) {
  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.centered}>
        {image && <Image source={{ uri: image.uri }} style={styles.preview} />}
        <ActivityIndicator size="large" style={{ marginTop: 20 }} />
        <Text style={styles.subtitle}>Scanning shelf... this can take a bit</Text>
      </View>
    </SafeAreaView>
  );
}

function ResultsScreen({
  scanResult, scanError, autoAdded, reviewQueue, onRetry, onScanAgain, onReview, onViewLibrary,
}) {
  if (scanError) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.centered}>
          <Text style={styles.title}>Scan failed</Text>
          <Text style={styles.subtitle}>{scanError}</Text>
          <View style={styles.buttonGroup}>
            <Button title="Retry" onPress={onRetry} />
            <Button title="Back" onPress={onScanAgain} />
          </View>
        </View>
      </SafeAreaView>
    );
  }

  const regionsFound = scanResult?.regions_found ?? 0;

  if (regionsFound === 0) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.centered}>
          <Text style={styles.title}>No books detected</Text>
          <Text style={styles.subtitle}>
            {scanResult?.detection_error
              ? `Detection error: ${scanResult.detection_error}`
              : "We couldn't find any book spines in that photo. Try a closer, well-lit shot."}
          </Text>
          <View style={styles.buttonGroup}>
            <Button title="Scan Again" onPress={onScanAgain} />
            <Button title="My Library" onPress={onViewLibrary} />
          </View>
        </View>
      </SafeAreaView>
    );
  }

  const errorCount = reviewQueue.filter((b) => b.status === 'error').length;
  const unreadableCount = reviewQueue.filter((b) => b.status === 'unreadable').length;
  const needsReviewCount = reviewQueue.length;

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.scrollContent}>
        <Text style={styles.title}>Scan Complete</Text>
        <Text style={styles.subtitle}>{regionsFound} book(s) detected</Text>

        <View style={styles.card}>
          <Text style={styles.cardHeading}>Added automatically: {autoAdded.length}</Text>
          {autoAdded.map((b, i) => (
            <Text key={i} style={styles.cardLine}>
              {b.match?.title} {b.match?.author ? `— ${b.match.author}` : ''}
            </Text>
          ))}
        </View>

        <View style={styles.card}>
          <Text style={styles.cardHeading}>Needs review: {needsReviewCount}</Text>
          {unreadableCount > 0 && (
            <Text style={styles.cardLine}>{unreadableCount} unreadable</Text>
          )}
          {errorCount > 0 && (
            <Text style={styles.cardLine}>{errorCount} failed to process</Text>
          )}
          {needsReviewCount > 0 && (
            <Button title="Review Now" onPress={onReview} />
          )}
        </View>

        <View style={styles.buttonGroup}>
          <Button title="Scan Again" onPress={onScanAgain} />
          <Button title="My Library" onPress={onViewLibrary} />
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

function ReviewScreen({ queue, onResolve, onDone }) {
  const handleConfirm = async (item) => {
    if (item.match) {
      await postToLibrary(item.match).catch(() => {});
    }
    onResolve(item._key);
  };

  const handleCorrect = async (item, candidate) => {
    await postToLibrary(candidate).catch(() => {});
    onResolve(item._key);
  };

  const handleDiscard = (item) => {
    onResolve(item._key);
  };

  if (queue.length === 0) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.centered}>
          <Text style={styles.title}>All caught up</Text>
          <Text style={styles.subtitle}>Nothing left to review.</Text>
          <Button title="Back to Results" onPress={onDone} />
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.scrollContent}>
        <Text style={styles.title}>Review ({queue.length})</Text>
        {queue.map((item) => (
          <View key={item._key} style={styles.card}>
            {item.status === 'error' && (
              <Text style={styles.cardHeading}>Couldn't process this one</Text>
            )}
            {item.status === 'unreadable' && (
              <Text style={styles.cardHeading}>Couldn't read this one</Text>
            )}
            {item.status === 'ok' && (
              <Text style={styles.cardHeading}>
                {item.detected_title}
                {item.detected_author ? ` — ${item.detected_author}` : ''}
              </Text>
            )}
            {item.status === 'error' && (
              <Text style={styles.cardLine}>Reason: {item.reason}</Text>
            )}

            {item.match && (
              <Text style={styles.cardLine}>
                Top match: {item.match.title} ({item.match.score}%)
              </Text>
            )}

            {item.candidates && item.candidates.length > 0 && (
              <View style={{ marginTop: 8 }}>
                <Text style={styles.cardLine}>Candidates:</Text>
                {item.candidates.map((c, i) => (
                  <TouchableOpacity
                    key={i}
                    onPress={() => handleCorrect(item, c)}
                    style={styles.candidateRow}
                  >
                    <Text style={styles.link}>
                      {c.title} {c.author ? `— ${c.author}` : ''} ({c.score}%)
                    </Text>
                  </TouchableOpacity>
                ))}
              </View>
            )}

            <View style={styles.buttonGroup}>
              {item.match && <Button title="Confirm" onPress={() => handleConfirm(item)} />}
              <Button title="Discard" color="#a33" onPress={() => handleDiscard(item)} />
            </View>
          </View>
        ))}
        <Button title="Back to Results" onPress={onDone} />
      </ScrollView>
    </SafeAreaView>
  );
}

function LibraryScreen({ onBack }) {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/library/`);
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      const data = await res.json();
      setEntries(data);
    } catch (err) {
      setError(err.message || 'Network request failed');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const onRefresh = () => {
    setRefreshing(true);
    load();
  };

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView
        contentContainerStyle={styles.scrollContent}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
      >
        <Text style={styles.title}>My Library</Text>
        {loading && <ActivityIndicator size="large" />}
        {error && (
          <View style={styles.centered}>
            <Text style={styles.subtitle}>{error}</Text>
            <Button title="Retry" onPress={load} />
          </View>
        )}
        {!loading && !error && entries.length === 0 && (
          <Text style={styles.subtitle}>No books yet. Go scan a shelf!</Text>
        )}
        {entries.map((entry) => (
          <View key={entry.id} style={styles.card}>
            <Text style={styles.cardHeading}>{entry.title}</Text>
            {!!entry.author && <Text style={styles.cardLine}>{entry.author}</Text>}
            <Text style={styles.cardLine}>
              Added {new Date(entry.added_at).toLocaleDateString()}
            </Text>
          </View>
        ))}
        <Button title="Back" onPress={onBack} />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  centered: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24, gap: 12 },
  scrollContent: { padding: 24, gap: 12 },
  title: { fontSize: 22, fontWeight: '700', marginBottom: 4 },
  subtitle: { fontSize: 14, color: '#555', textAlign: 'center', marginBottom: 12 },
  buttonGroup: { gap: 10, marginTop: 12, width: '100%' },
  linkButton: { marginTop: 20 },
  link: { color: '#2563eb', fontSize: 14 },
  preview: { width: 220, height: 220, borderRadius: 8 },
  card: {
    borderWidth: 1, borderColor: '#e2e2e2', borderRadius: 10,
    padding: 14, marginBottom: 12, backgroundColor: '#fafafa',
  },
  cardHeading: { fontSize: 16, fontWeight: '600', marginBottom: 4 },
  cardLine: { fontSize: 14, color: '#333', marginBottom: 2 },
  candidateRow: { paddingVertical: 4 },
});
