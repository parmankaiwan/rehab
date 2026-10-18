import net from "node:net";

const socket = net.createConnection({ host: "127.0.0.1", port: 3000 });

socket.setTimeout(1_000);
socket.once("connect", () => {
  socket.destroy();
  console.error(
    "Refusing to build while the FlexMap Next.js development server is running on port 3000. Stop it first, then rerun npm run build.",
  );
  process.exitCode = 1;
});
socket.once("timeout", () => {
  socket.destroy();
  process.exitCode = 0;
});
socket.once("error", (error) => {
  if (error.code === "ECONNREFUSED") {
    process.exitCode = 0;
    return;
  }
  console.error(`Unable to verify port 3000 before build: ${error.message}`);
  process.exitCode = 1;
});
