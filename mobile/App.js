import { useState, useCallback, useEffect } from 'react';
import {
  StyleSheet, Text, View, Button, Image, ScrollView,
  ActivityIndicator, TouchableOpacity, RefreshControl, SafeAreaView, Platform,
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
      if (Platform.OS === 'web') {
        // On web, ImagePicker returns a blob: URI. FormData needs a real
        // Blob/File appended, not the {uri, name, type} object React
        // Native's native FormData polyfill expects -- that shape silently
        // produces no file part in the multipart body on web, so the
        // backend sees no 'image' field and returns 400 immediately.
        let blob;
        try {
          blob = await (await fetch(imageAsset.uri)).blob();
        } catch {
          // A distinct message from the scan-request catch below --
          // otherwise a revoked blob: URL (can happen if the picker's
          // internal cleanup runs before this fetch) reads identically
          // to "server is down", and Retry re-fetches the same dead URI
          // forever since the underlying picked image is gone, not the
          // network.
          throw new Error('Could not read the selected image -- please pick it again.');
        }
        form.append('image', blob, imageAsset.fileName || 'shelf.jpg');
      } else {
        form.append('image', {
          uri: imageAsset.uri,
          name: imageAsset.fileName || 'shelf.jpg',
          type: imageAsset.mimeType || 'image/jpeg',
        });
      }
      const res = await fetch(`${API_BASE}/scan/`, { method: 'POST', body: form });
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      const data = await res.json();
      setScanResult(data);

      const books = data.books || [];
      const auto = books.filter((b) => b.status === 'ok' && b.band === 'auto');
      const needsReview = books.filter(
        (b) => b.status !== 'ok' || b.band !== 'auto'
      );

      // Await every auto-confirm before showing results -- previously
      // these were fire-and-forget, so a fast tap straight through to
      // My Library could load before some writes had landed (RN caps
      // concurrent connections per host, so a large batch serializes
      // into waves), and any that failed a 400 silently vanished from
      // both the count and the library. Only report success as success.
      const settled = await Promise.allSettled(auto.map((b) => postToLibrary(b.match)));
      const actuallyAdded = auto.filter((_, i) => settled[i].status === 'fulfilled');
      const failedToAdd = auto.length - actuallyAdded.length;

      setAutoAdded(actuallyAdded);
      setReviewQueue(needsReview.map((b, i) => ({ ...b, _key: `${i}-${Date.now()}` })));
      setScreen('results');
      if (failedToAdd > 0) {
        // Don't fail the whole scan over this -- surface it without
        // blocking the results screen the rest of the scan earned.
        console.warn(`${failedToAdd} auto-match(es) failed to save to the library.`);
      }
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
        sourceImage={lastImage}
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

async function postToLibrary({ title, author, isbn, score } = {}) {
  const res = await fetch(`${API_BASE}/library/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title, author: author || '', isbn: isbn || '', match_score: score }),
  });
  // fetch only rejects on a network failure -- a 400/500 resolves
  // normally, so without this check a failed save (e.g. a validation
  // error) looked identical to a successful one to every caller.
  if (!res.ok) throw new Error(`Library save failed: ${res.status}`);
  return res;
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

const THUMB_SIZE = 90;

// Crops a region of the full shelf photo down to a thumbnail using the
// [x1,y1,x2,y2] pixel box the backend already returns per book -- no
// backend change needed, just an oversized Image clipped to a fixed-size
// container and offset by the box's top-left corner.
function SpineThumbnail({ uri, box }) {
  const [naturalSize, setNaturalSize] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setNaturalSize(null); // clear stale size from a previous uri before re-measuring
    setFailed(false);
    Image.getSize(
      uri,
      (w, h) => { if (!cancelled) setNaturalSize({ w, h }); },
      () => { if (!cancelled) setFailed(true); }
    );
    return () => { cancelled = true; };
  }, [uri]);

  // getSize can fail on some URI shapes (Android content:// URIs, a
  // revoked web blob: URL) -- previously this left naturalSize null
  // forever with no fallback, so the card just showed an empty grey
  // square with no indication anything went wrong. Fall back to the
  // full (uncropped) photo, scaled down, rather than nothing.
  if (failed) {
    return (
      <View style={styles.thumbBox}>
        <Image source={{ uri }} style={{ width: THUMB_SIZE, height: THUMB_SIZE }} resizeMode="cover" />
      </View>
    );
  }

  if (!naturalSize || !box) {
    return <View style={[styles.thumbBox, styles.thumbPlaceholder]} />;
  }

  const [x1, y1, x2, y2] = box;
  const boxW = Math.max(x2 - x1, 1);
  const boxH = Math.max(y2 - y1, 1);
  const scale = Math.min(THUMB_SIZE / boxW, THUMB_SIZE / boxH);

  return (
    <View style={styles.thumbBox}>
      <Image
        source={{ uri }}
        style={{
          width: naturalSize.w * scale,
          height: naturalSize.h * scale,
          marginLeft: -x1 * scale,
          marginTop: -y1 * scale,
        }}
      />
    </View>
  );
}

const BAND_LABELS = {
  review: { text: 'Possible match — please confirm', color: '#b8860b' },
  none: { text: 'Low confidence — pick a candidate or discard', color: '#a33' },
};

function ReviewScreen({ queue, sourceImage, onResolve, onDone }) {
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
        {queue.map((item) => {
          const bandInfo = BAND_LABELS[item.band];
          // Only a "review"-band match (60-89%) is confident enough to
          // offer a one-tap Confirm. A "none"-band top match is little
          // more than noise -- surfacing it as confirmable invites
          // accidentally accepting a wrong book, so those only get
          // Correct (pick a candidate) or Discard.
          const canConfirm = item.match && item.band === 'review';

          return (
            <View key={item._key} style={styles.card}>
              <View style={styles.cardRow}>
                {sourceImage && item.box && (
                  <SpineThumbnail uri={sourceImage.uri} box={item.box} />
                )}
                <View style={styles.cardTextCol}>
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
                  {bandInfo && (
                    <Text style={[styles.cardLine, { color: bandInfo.color, fontWeight: '600' }]}>
                      {bandInfo.text}
                    </Text>
                  )}
                  {item.match && (
                    <Text style={styles.cardLine}>
                      Top match: {item.match.title} ({item.match.score}%)
                    </Text>
                  )}
                </View>
              </View>

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
                {canConfirm && <Button title="Confirm" onPress={() => handleConfirm(item)} />}
                <Button title="Discard" color="#a33" onPress={() => handleDiscard(item)} />
              </View>
            </View>
          );
        })}
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
  cardRow: { flexDirection: 'row', gap: 12 },
  cardTextCol: { flex: 1 },
  thumbBox: {
    width: THUMB_SIZE, height: THUMB_SIZE, borderRadius: 6,
    overflow: 'hidden', backgroundColor: '#eee',
  },
  thumbPlaceholder: { alignItems: 'center', justifyContent: 'center' },
});
