# 📷 Google Photos Uploader (Unlimited)

Proyek ini berbasis pada [google_photos_mobile_client](https://github.com/xob0t/google_photos_mobile_client) yang memungkinkan Anda untuk **memantau folder** (termasuk share SMB/NAS) dan **mengunggah foto ke Google Photos secara otomatis** tanpa mengurangi kuota penyimpanan, menggunakan kontainer Docker yang ringan.

---

## 🚀 Fitur Utama

- ✅ **Penyimpanan Tanpa Batas**: Mengunggah foto dalam kualitas asli tanpa memakan kuota storage Google (menggunakan identitas perangkat Pixel).
- 🔁 **Otomatisasi**: Memantau folder secara real-time dan langsung mengunggah file baru.
- 🗑️ **Auto-Clean Opsional**: Dapat menghapus file lokal setelah berhasil terunggah jika diaktifkan melalui environment.
- 🖥️ **Dashboard Real-time**: Pantau status unggahan, kecepatan, dan log melalui antarmuka web yang modern.
- 📁 **Fleksibel**: Bekerja dengan folder lokal maupun mount network (SMB/NAS).
- 🐳 **Dockerized**: Berjalan di dalam kontainer Docker minimalis.

---

## 📦 Kebutuhan Sistem

- Docker dan Docker Compose yang sudah terinstal.
- Folder berisi foto (atau mount SMB share).
- Kode otentikasi `AUTH_DATA` (lihat bagian cara mendapatkan kunci di bawah).

---

## ⚙️ Konfigurasi Docker Compose

Gunakan konfigurasi `docker-compose.yml` berikut:

```yaml
services:
  gphotos-uploader:
    build: .
    container_name: gphotos-uploader
    restart: unless-stopped
    environment:
      - WATCHED_FOLDER=/data
      - AUTH_DATA=ISI_DENGAN_AUTH_DATA_ANDA
      - DELETE_AFTER_UPLOAD=false
    volumes:
      - /jalur/ke/foto/anda:/data:z
      - ./uploader.db:/app/uploader.db:z # Optional: use this if you want a persistent database
    ports:
      - "8080:8080"
```

Ganti `/jalur/ke/foto/anda` dengan lokasi folder foto Anda di komputer host.

`DELETE_AFTER_UPLOAD` bernilai `false` secara default, sehingga file lokal tetap disimpan setelah unggahan berhasil. Set ke `true`, `1`, `yes`, atau `on` jika ingin menghapus file lokal otomatis setelah berhasil diunggah.

### Manual cleanup API

Use this endpoint from iOS Shortcuts to delete local files that were already uploaded successfully:

```http
POST http://SERVER_IP:8080/api/cleanup-uploaded
```

The endpoint uses the local SQLite upload history. It deletes only files whose latest local status is `Uploaded` or `Kept`, and only if the path is still inside `WATCHED_FOLDER`. By default it keeps history and writes `Deleted by cleanup` after successful file deletion.

To also remove that file's log rows from the database, add `purge=1`:

```http
POST http://SERVER_IP:8080/api/cleanup-uploaded?purge=1
```

Example response:

```json
{
  "status": "success",
  "checked": 3,
  "deleted": 2,
  "purge_db": false,
  "db_rows_deleted": 0,
  "skipped": [
    {
      "file": "/data/photo.jpg",
      "reason": "not found"
    }
  ],
  "errors": []
}
```

---

## ▶️ Cara Memulai

1. Buka terminal dan masuk ke folder proyek.
2. Jalankan kontainer:
   ```bash
   docker-compose up -d --build
   ```
3. Buka Dashboard di browser:
   `http://localhost:8080`
4. Cek log secara langsung:
   ```bash
   docker-compose logs -f
   ```

---

## 🔑 Cara Mendapatkan `AUTH_DATA`

Anda hanya perlu melakukan ini **satu kali** untuk mendapatkan kunci enkripsi permanen.

### ✅ Opsi 1 – Menggunakan ReVanced (Tanpa Root)

1. Instal Google Photos ReVanced di Android Anda:
   - Instal [GmsCore](https://github.com/ReVanced/GmsCore/releases).
   - Instal APK Google Photos yang sudah dipatch.
2. Hubungkan perangkat ke PC melalui ADB.
3. Jalankan perintah ini di terminal:
   - **Windows:** `adb logcat | FINDSTR "auth%2Fphotos.native"`
   - **Linux/macOS:** `adb logcat | grep "auth%2Fphotos.native"`
4. Buka aplikasi Google Photos ReVanced dan login.
5. Salin baris yang muncul mulai dari `androidId=...` hingga akhir. Itulah `AUTH_DATA` Anda! 🎉

---

## 🔄 Pembaruan

Untuk memperbarui aplikasi ke versi terbaru:

```bash
git pull
docker-compose up -d --build
```

---

## 💡 Catatan
- Secara default aplikasi **tidak menghapus** file lokal setelah berhasil diunggah. Aktifkan `DELETE_AFTER_UPLOAD=true` hanya jika Anda memang ingin auto-clean.
- Jika menggunakan SMB share, pastikan izin (permission) user kontainer sudah benar untuk membaca dan menghapus file.
- Proyek ini adalah implementasi praktis dari riset [google_photos_mobile_client](https://github.com/xob0t/google_photos_mobile_client).

---
