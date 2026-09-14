/** @type {import('next').NextConfig} */
const nextConfig = {
  // Emits a self-contained server bundle for the runtime Docker stage.
  output: "standalone",
  reactStrictMode: true,
};

export default nextConfig;
