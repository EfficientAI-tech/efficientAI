# Voice AI Evaluation Platform - Frontend

A modern React frontend for the Voice AI Evaluation Platform, built with TypeScript, Vite, Tailwind CSS, and React Query.

## Features

- 🔐 **API Key Authentication** - Secure login with API key management
- 📤 **Audio File Management** - Upload, view, and download audio files
- 📊 **Evaluation Creation** - Create ASR/TTS evaluations with customizable metrics
- 📈 **Real-time Status** - Monitor evaluation progress with automatic polling
- 📋 **Batch Processing** - Process multiple audio files in parallel
- 📊 **Results Visualization** - View detailed metrics and transcripts
- 🎨 **Modern UI** - Clean, responsive design with Tailwind CSS

## Tech Stack

- **React 18** - UI library
- **TypeScript** - Type safety
- **Vite** - Fast build tool and dev server
- **Tailwind CSS** - Utility-first CSS framework
- **React Router** - Client-side routing
- **TanStack Query** - Server state management
- **Zustand** - Client state management
- **Axios** - HTTP client
- **Lucide React** - Icon library

## Getting Started

### Prerequisites

- Node.js 18+ and npm/yarn/pnpm
- Backend API running on `http://localhost:8000` (or configure via environment variables)

### Installation

1. Navigate to the frontend directory:
```bash
cd frontend
```

2. Install dependencies:
```bash
npm install
# or
yarn install
# or
pnpm install
```

3. Create a `.env` file (optional, defaults provided):
```bash
cp .env.example .env
```

4. Start the development server:
```bash
npm run dev
```

The application will be available at `http://localhost:3000`

## Environment Variables

Create a `.env` file in the frontend directory:

```env
VITE_API_URL=http://localhost:8000
```

If not set, it defaults to `http://localhost:8000`

## Project Structure

```
frontend/
├── src/
│   ├── components/       # Reusable UI components
│   ├── pages/            # Page components
│   ├── lib/              # API client and utilities
│   ├── store/            # State management (Zustand)
│   ├── types/            # TypeScript type definitions
│   ├── App.tsx           # Main app component with routing
│   ├── main.tsx          # Entry point
│   └── index.css         # Global styles
├── public/               # Static assets
├── index.html            # HTML template
├── package.json          # Dependencies
├── vite.config.ts        # Vite configuration
├── tailwind.config.js    # Tailwind configuration
└── tsconfig.json         # TypeScript configuration
```

## Available Scripts

- `npm run dev` - Start development server
- `npm run build` - Build for production
- `npm run preview` - Preview production build
- `npm run lint` - Run ESLint

## Usage

### 1. Login

- If you don't have an API key, click "Generate New API Key" on the login page
- Enter a name for your key (optional)
- Save the generated key securely (you won't see it again)
- Enter your API key to sign in

### 2. Upload Audio Files

- Navigate to "Audio Files" from the sidebar
- Click "Upload Audio" button
- Select an audio file (WAV, MP3, FLAC, M4A)

### 3. Create Evaluations

- Click "New Evaluation" button
- Select an audio file
- Choose evaluation type (ASR or TTS)
- Select metrics to calculate (WER, CER, Latency, RTF, Quality Score)
- Optionally provide reference text for WER/CER calculation
- Click "Create Evaluation"

### 4. View Results

- Click on an evaluation to see details
- View transcript, metrics, and processing information
- Status updates automatically while processing

### 5. Batch Processing

- Navigate to "Batch Jobs"
- Click "New Batch Job"
- Select multiple audio files
- Configure evaluation settings
- Monitor progress and export results

## API Integration

The frontend communicates with the backend API using the API client in `src/lib/api.ts`. All requests automatically include the API key in the `X-API-Key` header.

### API Endpoints Used

- `POST /api/v1/auth/generate-key` - Generate API key
- `POST /api/v1/auth/validate` - Validate API key
- `GET /api/v1/audio` - List audio files
- `POST /api/v1/audio/upload` - Upload audio file
- `GET /api/v1/evaluations` - List evaluations
- `POST /api/v1/evaluations/create` - Create evaluation
- `GET /api/v1/results/{id}` - Get evaluation results
- `POST /api/v1/batch/create` - Create batch job
- `GET /api/v1/batch/{id}/results` - Get batch results

## Development

### Adding New Features

1. Create components in `src/components/`
2. Add pages in `src/pages/`
3. Update API client in `src/lib/api.ts` if needed
4. Add routes in `src/App.tsx`

### Styling

The project uses Tailwind CSS. Customize colors and themes in `tailwind.config.js`.

### State Management

- **Server State**: Use React Query (`@tanstack/react-query`) for API data
- **Client State**: Use Zustand (`src/store/`) for global app state (e.g., authentication)

## Building for Production

```bash
npm run build
```

The production build will be in the `dist/` directory.

## Troubleshooting

### CORS Issues

**API CORS (FastAPI):** If API calls fail from the browser, ensure `cors.origins` in `config.yml` includes your UI origin (typically `http://localhost:8000` when the API serves the SPA, plus `https://sandbox.efficientai.cloud` for hosted sandbox).

**S3 CORS (call-import uploads):** Staged CSV/XLSX and presigned audio uploads use `fetch(..., PUT)` **directly to S3**. That is a cross-origin request to `*.s3.amazonaws.com`, not to the API. The bucket must expose CORS allowing your app origin and `PUT`/`Content-Type`, or you will see:

`blocked by CORS policy ... No 'Access-Control-Allow-Origin' header`

Fix: apply bucket CORS once per environment (see `scripts/s3-bucket-cors-call-imports.example.json`):

```bash
export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... AWS_DEFAULT_REGION=us-east-1
./scripts/apply_s3_call_import_cors.sh --config config.yml
# or: aws s3api put-bucket-cors --bucket voiceai-evals-test --cors-configuration file://scripts/s3-bucket-cors-call-imports.example.json
```

Edit `AllowedOrigins` in that file first (localhost + production URL).

**401 on `/api/v1/...`:** Session or API key expired — sign in again. A failed S3 PUT often appears as a separate CORS error, not 401.

### API Key Issues

- Ensure your API key is valid
- Check that the backend is running
- Verify the API URL in `.env` matches your backend

### Build Errors

- Clear `node_modules` and reinstall: `rm -rf node_modules && npm install`
- Check Node.js version (requires 18+)
- Ensure TypeScript types are correct

## License

MIT License - see LICENSE file for details

