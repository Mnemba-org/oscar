# BVD - Baraza la Vijana Dodo (Flask App)

Mfumo mmoja wa Flask unaosimamia tovuti nzima ya Baraza la Vijana Dodo:
usajili wa wanachama, login, dashboard ya wanachama, matangazo, miradi,
viongozi, admin panel, na export ya CSV/PDF.

## Vipengele Muhimu

- **Login ya lazima** kwa kila mtumiaji — kwa namba ya simu (mfumo `0xxxxxxxxx`) na password.
- **Namba ya uanachama ya kipekee** kwa mfumo `BVD/0001`, `BVD/0002` ... inayotolewa moja kwa moja mtu anapojiunga.
- **Umri unahesabiwa** kutoka tarehe ya kuzaliwa (DOB) na kuhifadhiwa kwenye database; unasasishwa moja kwa moja (mfano siku ya kuzaliwa ikifika, mara wanachama/dashboard inapofunguliwa upya).
- **Admin dhidi ya Mwanachama wa kawaida**: wote wanaona ukurasa uleule (Miradi, Matangazo, Viongozi, Wanachama) lakini **Admin** pekee anaona vitufe vya "Ongeza" na "Futa", anaweza kuongeza Admin mwingine, na kupakua taarifa za wanachama (CSV/PDF).
- **Usalama wa password**: password zote zinahifadhiwa kwa hashing (bcrypt) — hazihifadhiwi wazi kamwe.
- Database inatumia **PostgreSQL kupitia Supabase**, ikisimamiwa na SQLAlchemy.

## Muundo wa Faili

```
bvd_flask/
├── app.py                 # App moja inayosimamia mfumo mzima (models + routes)
├── requirements.txt
├── Procfile                # Kwa Render (gunicorn)
├── .env.example             # Mfano wa environment variables
├── static/
│   ├── css/style.css
│   └── uploads/             # Picha zinazopakiwa (leaders, projects, n.k.)
└── templates/                # Kurasa za HTML (Jinja2)
```

## Hatua za Deploy

### 1. Tengeneza Database kwenye Supabase
1. Fungua [supabase.com](https://supabase.com) na tengeneza project mpya.
2. Nenda **Project Settings → Database → Connection string → URI**.
3. Nakili connection string (inaanza na `postgresql://postgres:...`).
   - Kama unatumia **Render free tier**, tumia URL ya "Connection Pooling" (Transaction mode) badala ya ile ya moja kwa moja, kwani Render free haiungi mkono IPv6 ambayo Supabase direct connection wakati mwingine inahitaji.

### 2. Pakia Code GitHub
```bash
cd bvd_flask
git init
git add .
git commit -m "BVD Flask app"
git branch -M main
git remote add origin https://github.com/JINA_LAKO/bvd-flask.git
git push -u origin main
```
Faili la `.env` na `static/uploads/*` (isipokuwa `.gitkeep`) halitapakiwa kwa sababu ya `.gitignore`.

### 3. Tengeneza Web Service kwenye Render
1. Render Dashboard → **New → Web Service** → unganisha na repo yako ya GitHub.
2. **Build Command:** `pip install -r requirements.txt`
3. **Start Command:** `gunicorn app:app`
4. Nenda **Environment** → ongeza Environment Variables zifuatazo:

| Key | Thamani |
|---|---|
| `SECRET_KEY` | string ndefu ya nasibu (unaweza kutumia `python -c "import secrets; print(secrets.token_hex(32))"`) |
| `DATABASE_URL` | connection string yako ya Supabase (kutoka hatua ya 1) |
| `ADMIN_PHONE` | namba ya simu ya admin wa kwanza, mfano `0712345678` |
| `ADMIN_PASSWORD` | password ya admin wa kwanza (badilisha baada ya login ya kwanza ikiwezekana) |

5. Bofya **Deploy**. Wakati app inapoanza mara ya kwanza, itatengeneza tables zote za database kwenye Supabase moja kwa moja, na kutengeneza akaunti ya Admin wa kwanza kutoka `ADMIN_PHONE`/`ADMIN_PASSWORD`.

### 4. Baada ya Deploy
- Ingia kama admin kwa `ADMIN_PHONE` na `ADMIN_PASSWORD` uliyoweka.
- Kutoka **Admin Panel**, unaweza kuongeza Admin wengine, Matangazo, Miradi, Viongozi.
- Wanachama wapya wanaweza kujisajili kupitia ukurasa wa **Jiunge**.

## Kuendesha Kwenye Kompyuta Yako (Local)

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # kisha jaza thamani zako
export $(cat .env | xargs)         # au tumia python-dotenv
python app.py
```
Kama huweki `DATABASE_URL`, app itatumia SQLite ya ndani (`bvd_local.db`) kiotomatiki — nzuri kwa majaribio kabla ya kwenda Supabase.

## Maelezo ya Usalama
- Password zote zinahifadhiwa kwa **bcrypt hashing** (`Flask-Bcrypt`) — si maandishi wazi.
- Session inasimamiwa na `Flask-Login`.
- Sehemu za Admin (`/admin/*`, kuongeza/kufuta rekodi) zimefungwa na `@admin_required` decorator — mtumiaji wa kawaida akijaribu kufikia, anarudishwa na ujumbe wa onyo.
- Weka `SECRET_KEY` na `DATABASE_URL` kama Environment Variables kwenye Render TU — kamwe usiziandike ndani ya code au kuzipakia GitHub.
