/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Tauri / static export is enabled later in Phase 6 by setting `output: 'export'`.
  async rewrites() {
    return [
      { source: "/api/:path*", destination: "http://localhost:8000/api/:path*" },
      { source: "/sse/:path*", destination: "http://localhost:8000/sse/:path*" },
      { source: "/ws/:path*", destination: "http://localhost:8000/ws/:path*" },
    ];
  },
};

export default nextConfig;
