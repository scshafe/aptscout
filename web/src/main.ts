import { mount } from "svelte";
import App from "./App.svelte";
import "maplibre-gl/dist/maplibre-gl.css";
import "./app.css";

export default mount(App, { target: document.getElementById("app")! });

if (import.meta.env.PROD && "serviceWorker" in navigator && window.isSecureContext) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});  // offline support is a convenience
}
