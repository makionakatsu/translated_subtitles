import { NewJobForm } from "@/components/NewJobForm";
import { JobDock } from "@/components/JobDock";

export default function Home() {
  return (
    <main className="min-h-dvh px-6 py-10 max-w-3xl mx-auto">
      <header className="mb-8 space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">字幕制作スイート</h1>
        <p className="text-sm text-muted">
          Apple Silicon の mlx-whisper と Gemini で、字幕を生成・翻訳・編集します。
        </p>
      </header>
      <NewJobForm />
      <JobDock />
    </main>
  );
}
