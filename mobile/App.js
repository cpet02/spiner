import { useState } from 'react';
import { StyleSheet, Text, View, Button, Image } from 'react-native';
import * as ImagePicker from 'expo-image-picker';

// TODO: point at your machine's LAN IP once the backend endpoint exists.
const API_BASE = 'http://192.168.1.X:8000/api';

export default function App() {
  const [image, setImage] = useState(null);

  const pickImage = async () => {
    const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) return;
    const picked = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      quality: 0.7,
    });
    if (!picked.canceled) setImage(picked.assets[0]);
  };

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Shelfie</Text>
      <Button title="Pick a bookshelf photo" onPress={pickImage} />
      {image && <Image source={{ uri: image.uri }} style={styles.preview} />}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24, gap: 12 },
  title: { fontSize: 20, fontWeight: '600', marginBottom: 12 },
  preview: { width: 240, height: 240, borderRadius: 8, marginTop: 12 },
});
