import pytest

from app import create_app, kategori_gula, kategori_tensi


@pytest.fixture
def app(tmp_path):
    return create_app({"TESTING": True, "CSRF_ENABLED": False, "DATABASE": str(tmp_path / "test.db")})


@pytest.fixture
def anon(app):
    return app.test_client()


@pytest.fixture
def client(app):
    c = app.test_client()
    r = c.post("/setup", data={"username": "admin", "password": "rahasia123", "konfirmasi": "rahasia123"})
    assert r.status_code == 302
    return c


def test_kategori():
    assert kategori_tensi(115, 75)[0] == "Normal"
    assert kategori_tensi(125, 75)[0] == "Meningkat"
    assert kategori_tensi(135, 85)[0] == "Hipertensi Tahap 1"
    assert kategori_tensi(150, 95)[0] == "Hipertensi Tahap 2"
    assert kategori_tensi(190, 100)[0] == "Krisis Hipertensi"
    assert kategori_gula(90, "puasa")[0] == "Normal"
    assert kategori_gula(110, "puasa")[0] == "Prediabetes"
    assert kategori_gula(130, "puasa")[0] == "Diabetes"
    assert kategori_gula(130, "sewaktu")[0] == "Normal"
    assert kategori_gula(250, "sewaktu")[0] == "Diabetes"
    assert kategori_gula(60, "sewaktu")[0] == "Hipoglikemia"


def test_alur_lengkap(client):
    r = client.post("/pasien/baru", data={"nama": "Budi Santoso", "no_rm": "RM001", "jenis_kelamin": "L"})
    assert r.status_code == 302
    pid = int(r.headers["Location"].rstrip("/").split("/")[-1])

    r = client.post(f"/pasien/{pid}/pengukuran/baru", data={
        "waktu": "2026-10-05T08:00", "sistolik": "150", "diastolik": "95", "nadi": "88",
        "gula_darah": "180", "jenis_gula": "sewaktu",
    })
    assert r.status_code == 302

    r = client.post(f"/pasien/{pid}/obat/baru", data={
        "nama": "Amlodipine", "dosis": "5", "satuan": "mg", "rute": "Oral", "frekuensi": "1x sehari",
        "tanggal_mulai": "2026-10-05", "tanggal_selesai": "2026-10-07",
    })
    assert r.status_code == 302
    oid = int(r.headers["Location"].split("/")[-3])

    r = client.post(f"/obat/{oid}/jadwal/baru", data={
        "tanggal_mulai": "2026-10-05", "tanggal_selesai": "2026-10-07", "jam": "08:00, 20:00",
    }, follow_redirects=True)
    assert "6 jadwal pemberian Amlodipine dibuat" in r.get_data(as_text=True)

    # duplicate generation is skipped
    r = client.post(f"/obat/{oid}/jadwal/baru", data={
        "tanggal_mulai": "2026-10-05", "tanggal_selesai": "2026-10-05", "jam": "08:00",
    }, follow_redirects=True)
    assert "0 jadwal pemberian" in r.get_data(as_text=True)

    html = client.get(f"/pasien/{pid}").get_data(as_text=True)
    assert "150/95" in html and "Hipertensi Tahap 2" in html
    assert "Amlodipine" in html and "5 mg" in html

    r = client.post("/jadwal/1/status", data={"status": "diberikan", "next": "//evil.com"})
    assert r.headers["Location"].startswith("/pasien/")
    html = client.get("/?tanggal=2026-10-05").get_data(as_text=True)
    assert "Budi Santoso" in html and "Diberikan" in html


def test_validasi(client):
    client.post("/pasien/baru", data={"nama": "Ani"})
    r = client.post("/pasien/1/pengukuran/baru", data={"waktu": "2026-10-05T08:00"})
    assert "Isi minimal tensi atau gula darah" in r.get_data(as_text=True)
    r = client.post("/pasien/1/pengukuran/baru", data={"waktu": "2026-10-05T08:00", "sistolik": "120"})
    assert "Isi sistolik dan diastolik sekaligus" in r.get_data(as_text=True)
    r = client.post("/pasien/baru", data={"nama": ""})
    assert "Nama pasien wajib diisi" in r.get_data(as_text=True)


def test_edit_pasien_nama_kosong(client):
    client.post("/pasien/baru", data={"nama": "Ani"})
    r = client.post("/pasien/1/edit", data={"nama": "   "})
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Nama pasien wajib diisi" in html and 'href="/pasien/1"' in html


def test_obat_tanggal_terbalik_saat_tambah(client):
    client.post("/pasien/baru", data={"nama": "Ani"})
    r = client.post("/pasien/1/obat/baru", data={
        "nama": "Metformin", "dosis": "500", "tanggal_mulai": "2026-10-10", "tanggal_selesai": "2026-10-05",
    })
    assert "Tanggal selesai tidak boleh sebelum tanggal mulai" in r.get_data(as_text=True)


def test_setup_lalu_login(anon):
    assert anon.get("/").headers["Location"].endswith("/setup")
    r = anon.post("/setup", data={"username": "admin", "password": "pendek", "konfirmasi": "pendek"})
    assert "Password minimal 8 karakter" in r.get_data(as_text=True)
    anon.post("/setup", data={"username": "admin", "password": "rahasia123", "konfirmasi": "rahasia123"})
    assert anon.get("/").status_code == 200
    anon.post("/logout")
    assert "/login" in anon.get("/pasien").headers["Location"]
    # setup is closed once a user exists
    assert anon.get("/setup").headers["Location"].endswith("/login")
    r = anon.post("/login", data={"username": "admin", "password": "salah"})
    assert r.status_code == 401
    r = anon.post("/login?next=/pasien", data={"username": "ADMIN", "password": "rahasia123"})
    assert r.headers["Location"] == "/pasien"


def test_kelola_pengguna_dan_ganti_password(client, app):
    client.post("/pengguna", data={"username": "perawat", "password": "perawat123", "konfirmasi": "perawat123"})
    r = client.post("/pengguna", data={"username": "perawat", "password": "perawat123", "konfirmasi": "perawat123"})
    assert "sudah dipakai" in r.get_data(as_text=True)
    r = client.post("/akun/password", data={"password_lama": "salah", "password": "baru12345", "konfirmasi": "baru12345"})
    assert "Password lama salah" in r.get_data(as_text=True)
    client.post("/akun/password", data={"password_lama": "rahasia123", "password": "baru12345", "konfirmasi": "baru12345"})
    client.post("/logout")
    other = app.test_client()
    assert other.post("/login", data={"username": "admin", "password": "baru12345"}).status_code == 302
    r = other.post("/pengguna/1/hapus", follow_redirects=True)
    assert "Tidak bisa menghapus akun sendiri" in r.get_data(as_text=True)


def test_csrf(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "csrf.db")})
    c = app.test_client()
    assert c.post("/setup", data={"username": "a", "password": "rahasia123", "konfirmasi": "rahasia123"}).status_code == 400
    html = c.get("/setup").get_data(as_text=True)
    token = html.split('name="csrf_token" value="')[1].split('"')[0]
    r = c.post("/setup", data={"csrf_token": token, "username": "a", "password": "rahasia123", "konfirmasi": "rahasia123"})
    assert r.status_code == 302


def test_cli_set_password(app):
    runner = app.test_cli_runner()
    r = runner.invoke(args=["set-password", "admin"], input="rahasia123\nrahasia123\n")
    assert "dibuat" in r.output
    c = app.test_client()
    assert c.post("/login", data={"username": "admin", "password": "rahasia123"}).status_code == 302


def _login(app, username, password):
    c = app.test_client()
    assert c.post("/login", data={"username": username, "password": password}).status_code == 302
    return c


def test_akses_pasien_per_petugas(client, app):
    for u in ("siti", "rina"):
        client.post("/pengguna", data={"username": u, "role": "petugas", "password": "petugas123", "konfirmasi": "petugas123"})
    # siti = id 2, rina = id 3; admin (id 1) is ignored as an assignee
    client.post("/pasien/baru", data={"nama": "Budi", "petugas": ["2", "1"]})
    client.post("/pasien/baru", data={"nama": "Wati", "petugas": ["3"]})
    client.post("/pasien/1/obat/baru", data={"nama": "Amlodipine", "dosis": "5"})
    client.post("/pasien/2/obat/baru", data={"nama": "Metformin", "dosis": "500"})
    client.post("/obat/2/jadwal/baru", data={"tanggal_mulai": "2026-10-05", "tanggal_selesai": "2026-10-05", "jam": "08:00"})
    client.post("/pasien/2/pengukuran/baru", data={"waktu": "2026-10-05T08:00", "gula_darah": "120"})

    siti = _login(app, "siti", "petugas123")
    html = siti.get("/pasien").get_data(as_text=True)
    assert "Budi" in html and "Wati" not in html
    html = siti.get("/?tanggal=2026-10-05").get_data(as_text=True)
    assert "Wati" not in html and "Metformin" not in html
    assert siti.get("/pasien/1").status_code == 200
    # every route touching another patient's data is 404
    for url in ("/pasien/2", "/pasien/2/edit", "/pasien/2/obat/baru", "/pasien/2/pengukuran/baru",
                "/obat/2/edit", "/obat/2/jadwal/baru", "/pengukuran/1/edit"):
        assert siti.get(url).status_code == 404, url
    for url, data in (("/pasien/2/edit", {"nama": "X"}), ("/obat/2/hapus", {}), ("/pengukuran/1/hapus", {}),
                      ("/jadwal/1/status", {"status": "diberikan"}), ("/jadwal/1/hapus", {})):
        assert siti.post(url, data=data).status_code == 404, url
    # admin-only actions
    for url in ("/pasien/baru", "/pengguna"):
        assert siti.get(url).status_code == 403, url
    assert siti.post("/pasien/1/hapus").status_code == 403
    assert siti.post("/pengguna/3/role", data={"role": "admin"}).status_code == 403
    # petugas can still manage an assigned patient, but not change its assignment
    assert siti.post("/pasien/1/edit", data={"nama": "Budi S", "petugas": ["3"]}).status_code == 302
    assert siti.post("/pasien/1/pengukuran/baru", data={"waktu": "2026-10-05T09:00", "sistolik": "120", "diastolik": "80"}).status_code == 302
    assert _login(app, "rina", "petugas123").get("/pasien/1").status_code == 404

    # admin sees everything and can reassign
    assert "Wati" in client.get("/pasien").get_data(as_text=True)
    client.post("/pasien/2/edit", data={"nama": "Wati", "petugas": ["2"]})
    assert siti.get("/pasien/2").status_code == 200


def test_ubah_role(client, app):
    client.post("/pengguna", data={"username": "siti", "role": "petugas", "password": "petugas123", "konfirmasi": "petugas123"})
    client.post("/pasien/baru", data={"nama": "Budi"})
    siti = _login(app, "siti", "petugas123")
    assert siti.get("/pasien/1").status_code == 404
    client.post("/pengguna/2/role", data={"role": "admin"})
    assert siti.get("/pasien/1").status_code == 200 and siti.get("/pengguna").status_code == 200
    r = client.post("/pengguna/1/role", data={"role": "petugas"}, follow_redirects=True)
    assert "Tidak bisa mengubah role akun sendiri" in r.get_data(as_text=True)


def test_migrasi_pengguna_lama_jadi_admin(tmp_path):
    import sqlite3
    from werkzeug.security import generate_password_hash
    path = tmp_path / "lama.db"
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE pengguna (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            nama TEXT, password_hash TEXT NOT NULL, dibuat TEXT NOT NULL DEFAULT (datetime('now', 'localtime')));
        CREATE TABLE pasien (id INTEGER PRIMARY KEY AUTOINCREMENT, no_rm TEXT, nama TEXT NOT NULL, tanggal_lahir TEXT,
            jenis_kelamin TEXT, catatan TEXT, dibuat TEXT NOT NULL DEFAULT (datetime('now', 'localtime')));
    """)
    db.execute("INSERT INTO pengguna (username, password_hash) VALUES ('lama', ?)", (generate_password_hash("rahasia123"),))
    db.execute("INSERT INTO pasien (nama) VALUES ('Budi')")
    db.commit()
    db.close()
    app = create_app({"TESTING": True, "CSRF_ENABLED": False, "DATABASE": str(path)})
    c = _login(app, "lama", "rahasia123")
    assert "Budi" in c.get("/pasien").get_data(as_text=True)
    assert c.get("/pengguna").status_code == 200
    # new users created afterwards default to petugas
    c.post("/pengguna", data={"username": "baru", "password": "rahasia123", "konfirmasi": "rahasia123"})
    assert _login(app, "baru", "rahasia123").get("/pasien/1").status_code == 404
