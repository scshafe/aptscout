import { mount } from "svelte";
import App from "./App.svelte";
import "maplibre-gl/dist/maplibre-gl.css";
import "./app.css";

export default mount(App, { target: document.getElementById("app")! });
