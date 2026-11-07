import HealthStatus from "./health-status";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-xl flex-1 flex-col gap-6 px-6 py-16">
      <h1 className="text-3xl font-semibold tracking-tight">Ward</h1>
      <HealthStatus />
    </main>
  );
}
