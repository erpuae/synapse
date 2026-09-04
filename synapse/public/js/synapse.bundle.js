// Copyright (c) 2026, Dxbitz and contributors
// Entry point for the Synapse component library bundle. Frappe's build compiles
// this file (esbuild resolves the imports) and it is included on the desk by the
// app_include_js hook. It exposes the library on one global namespace so the
// page grid (M1) and the demo harness read the same registry.

import { render, resolve, RENDERERS, known_types } from "./library/registry.js";
import { renderPage } from "./library/grid.js";

frappe.provide("synapse.library");
synapse.library.render = render;
synapse.library.resolve = resolve;
synapse.library.renderers = RENDERERS;
synapse.library.known_types = known_types;
synapse.library.render_page = renderPage;
