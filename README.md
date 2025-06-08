# SolCraft L2 Backend

Backend per la piattaforma di tokenizzazione SolCraft L2 su blockchain Solana.

## Configurazione Deploy con GitHub Actions

Questo repository è configurato per il deploy automatico su Vercel tramite GitHub Actions. Il workflow è definito nel file `.github/workflows/vercel-deploy.yml`.

### Prerequisiti

Per utilizzare il workflow di deploy automatico, è necessario configurare i seguenti segreti nel repository GitHub:

- `VERCEL_TOKEN`: Token di accesso per l'API Vercel
- `VERCEL_ORG_ID`: ID dell'organizzazione Vercel
- `VERCEL_PROJECT_ID`: ID del progetto Vercel (prj_2Dh9UFSJ6Ul2DGxyJydFwQGAhLsu)
- `POSTGRES_URL`: URL di connessione al database PostgreSQL su Supabase
- `DATABASE_URL`: URL di connessione al database (stesso valore di POSTGRES_URL)
- `SUPABASE_URL`: URL del progetto Supabase
- `SUPABASE_KEY`: Chiave API di Supabase
- `JWT_SECRET`: Chiave segreta per la generazione dei token JWT
- `SMTP_HOST`: Host del server SMTP per l'invio di email
- `SMTP_PORT`: Porta del server SMTP
- `SMTP_USER`: Username per l'autenticazione SMTP
- `SMTP_PASS`: Password per l'autenticazione SMTP

### Come ottenere i segreti Vercel

1. **VERCEL_TOKEN**:
   - Vai su https://vercel.com/account/tokens
   - Crea un nuovo token con nome "GitHub Actions"
   - Copia il token generato

2. **VERCEL_ORG_ID e VERCEL_PROJECT_ID**:
   - Installa Vercel CLI: `npm i -g vercel`
   - Esegui `vercel login` e accedi con il tuo account
   - Esegui `vercel link` nella directory del progetto
   - I valori di ORG_ID e PROJECT_ID saranno salvati nel file `.vercel/project.json`

### Come ottenere i segreti Supabase

1. **SUPABASE_URL e SUPABASE_KEY**:
   - Vai su https://app.supabase.io/
   - Seleziona il tuo progetto
   - Vai su Settings > API
   - Copia "URL" e "anon/public key"

### Trigger del Deploy

Il deploy viene avviato automaticamente in due casi:
- Push sul branch `main`
- Avvio manuale del workflow tramite l'interfaccia di GitHub Actions

## Connessione al Database

Il backend utilizza PostgreSQL su Supabase come database. La connessione è configurata tramite le variabili d'ambiente `POSTGRES_URL` e `DATABASE_URL`.

## Struttura del Progetto

- `/api`: Endpoint API Flask
- `/models`: Modelli di dati
- `/services`: Logica di business
- `/utils`: Utility e helper functions

## Sviluppo Locale

1. Clona il repository
2. Installa le dipendenze: `npm install`
3. Crea un file `.env` con le variabili d'ambiente necessarie:
   ```
   DATABASE_URL=postgresql://postgres:postgres@db.solcraftl2.supabase.co:5432/postgres
   POSTGRES_URL=postgresql://postgres:postgres@db.solcraftl2.supabase.co:5432/postgres
   SUPABASE_URL=https://db.solcraftl2.supabase.co
   SUPABASE_KEY=your-supabase-key
   JWT_SECRET=your-jwt-secret
   SMTP_HOST=smtp.example.com
   SMTP_PORT=587
   SMTP_USER=your-smtp-user
   SMTP_PASS=your-smtp-password
   ```
4. Avvia il server di sviluppo: `vercel dev`
