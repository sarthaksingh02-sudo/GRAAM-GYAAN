# Vercel frontend + Render backend

This configuration uses the existing SQLite database in temporary storage on the free Render plan. Saved data and audio may reset on restart. The UI displays this limitation.
Supabase is not yet supported by the SQLite-specific queries; do not put a Postgres URL in DATABASE_URL.
For durable storage later, attach a paid Render disk and point DATA_DIR and DATABASE_URL at its mount path, or implement a Postgres migration.

1. Push the reviewed application changes to your GitHub repository.
2. In Render, create a Blueprint from the repository and review render.yaml. Set SARVAM_API_KEY privately in Render. Never put it in a VITE_ variable or commit .env.
3. Note the actual HTTPS backend URL. Replace both graam-gyaan-api.onrender.com destinations in frontend/vercel.json if Render assigned a different hostname.
4. Import the repository into Vercel. Root directory: frontend. Framework: Vite. Build: npm run build. Output: dist.
5. Set Render ALLOWED_ORIGINS to your exact Vercel HTTPS origin. The frontend proxies /api and /healthz through Vercel, keeping session cookies and audio on the same origin.
6. Verify /healthz on the Vercel domain, complete consent, save a location, send a chat, play audio, then open a private browser and verify the first browser's household is not visible.

DEPLOYMENT_MODE=public creates a separate, anonymous household per browser with an HTTP-only secure cookie. Clearing the cookie loses access; account login and recovery are not implemented. Do not seed a real household onto the public instance. Personal API responses are marked private, no-store.

Use a single backend worker with SQLite. Uploaded documents are temporary and deleted after processing; generated audio and the database use /tmp/graam-gyaan. Back up any data before replacing the service. Free ephemeral hosting would lose saved households on restart and is unsuitable for persistent data.

Do not claim a live deployment until the public frontend and backend have been tested. localhost is not a submission deployment link.
