export default function Home() {
  return (
    <main className="min-h-dvh flex flex-col items-center justify-center gap-4 p-8">
      <h1 className="text-3xl font-semibold">字幕制作スイート</h1>
      <p className="text-muted">
        Phase 0 skeleton — editor UI lands in Phase 3.
      </p>
      <a
        href="http://localhost:8000/health"
        className="text-accent underline underline-offset-4"
        target="_blank"
        rel="noreferrer"
      >
        API health endpoint →
      </a>
    </main>
  );
}
