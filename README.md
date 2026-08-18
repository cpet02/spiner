# Shelfie — Bookshelf → Library

Take-home project: photo of a bookshelf → structured personal library.

## Status
Initial scaffold only. Backend (Django REST) and mobile (Expo) skeletons
are wired up; the detection/VLM/matching pipeline is built in subsequent
commits. See commit history for progression.

## Structure
- `backend/` — Django REST Framework, model calls isolated in `vision/ai_client.py`
- `mobile/` — Expo (React Native)

## Backend setup
```
cd backend
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
cp .env.example .env   # add your OPENROUTER_API_KEY
./venv/bin/python manage.py migrate
./venv/bin/python manage.py runserver 0.0.0.0:8000
```

## Mobile setup
```
cd mobile
npm install
npx expo start
```
Update `API_BASE` in `App.js` to your machine's LAN IP once endpoints exist.

## Design notes
- All AI model calls route through `vision/ai_client.py` (OpenRouter).
  Swapping providers or models means editing this file only.
- CORS wide open in dev — Expo's dev server origin varies by machine.

This README will be replaced with the full architecture/decisions writeup
in the final commit.
