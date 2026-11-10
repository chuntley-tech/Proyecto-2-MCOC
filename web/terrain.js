'use strict';

// Proyección ortográfica de una malla de elevaciones en ejes este/norte.
class TerrainView {
  constructor(panel, terrain, image) {
    this.canvas = panel.querySelector('canvas');
    this.north = panel.querySelector('.terrain-north span');
    this.scaleBar = panel.querySelector('.terrain-scale span');
    this.zoomLabel = panel.querySelector('#terrain-zoom-level');
    this.layer = panel.querySelector('#terrain-layer');
    this.layerStatus = panel.querySelector('#terrain-layer-status');
    this.imageryCredit = panel.querySelector('#terrain-imagery-credit');
    this.hasImage = Boolean(image);
    this.layer.querySelector('[value="satellite"]').disabled = !image;
    this.extent = terrain.extent_m;
    const {samples, elevation_m: heights} = terrain;
    if (!Number.isInteger(samples) || samples < 3 || samples % 2 !== 1 ||
        !Number.isFinite(this.extent) || this.extent <= 0 ||
        heights.length !== samples ** 2 || !heights.every(Number.isFinite)) {
      throw Error('La malla de elevaciones no es válida.');
    }
    this.spacing = this.extent / (samples - 1);
    this.elevation = heights[(heights.length - 1) / 2];
    const relief = Math.max(1, Math.max(...heights) - Math.min(...heights));
    const low = Math.min(...heights);
    this.elevationRange = [low, relief];
    const colors = image ? this.sampleImage(image, samples) : null;
    this.points = heights.map((z, i) => [
      (i % samples) * this.spacing - this.extent / 2,
      Math.floor(i / samples) * this.spacing - this.extent / 2,
      (z - this.elevation) * 3
    ]);
    this.faces = [];
    for (let y = 0; y < samples - 1; y++) {
      for (let x = 0; x < samples - 1; x++) {
        const a = y * samples + x;
        const b = a + 1, c = a + samples + 1, d = a + samples;
        this.faces.push(this.face([a, b, c], low, relief, colors), this.face([a, c, d], low, relief, colors));
      }
    }
    if (image) this.gl = this.canvas.getContext('webgl2', {antialias: true});
    if (this.gl) {
      try {
        this.initTexture(image);
      } catch {
        const replacement = this.canvas.cloneNode();
        this.canvas.replaceWith(replacement);
        this.canvas = replacement;
        this.gl = null;
      }
    }
    if (!this.gl) this.context = this.canvas.getContext('2d');
    this.reset();
    this.bindCamera(panel);
    this.observer = new ResizeObserver(() => this.scheduleDraw());
    this.observer.observe(this.canvas);
  }

  sampleImage(image, size) {
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = size;
    const ctx = canvas.getContext('2d');
    // El raster empieza al norte, mientras los vértices empiezan al sur.
    ctx.setTransform(1, 0, 0, -1, 0, size);
    ctx.drawImage(image, 0, 0, size, size);
    return ctx.getImageData(0, 0, size, size).data;
  }

  face(indices, low, relief, colors) {
    const [a, b, c] = indices.map(i => this.points[i]);
    const ux = b[0] - a[0], uy = b[1] - a[1], uz = b[2] - a[2];
    const vx = c[0] - a[0], vy = c[1] - a[1], vz = c[2] - a[2];
    const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
    const light = Math.max(0, (-.48 * nx + .42 * ny + .77 * nz) / Math.hypot(nx, ny, nz));
    const elevation = ((a[2] + b[2] + c[2]) / 9 + this.elevation - low) / relief;
    const shade = .84 + .28 * light;
    const reliefColor = [41 + elevation * 168, 94 + elevation * 103, 94 + elevation * 60].map(v => v * shade);
    const photoColor = colors
      ? [0, 1, 2].map(channel => {
        const mean = indices.reduce((sum, i) => sum + colors[i * 4 + channel], 0) / (3 * 255);
        return 255 * mean ** .80 * shade;
      })
      : reliefColor;
    return {indices, shade, photoColor, reliefColor, depth: 0};
  }

  initTexture(image) {
    const gl = this.gl;
    const vertex = `#version 300 es
      layout(location=0) in vec3 point;
      layout(location=1) in float shade;
      uniform vec4 camera;
      uniform vec2 scale;
      uniform float extent;
      uniform float referenceElevation;
      out vec2 uv;
      out float light;
      out float elevation;
      void main() {
        float x = camera.x * point.x - camera.y * point.y;
        float y = camera.y * point.x + camera.x * point.y;
        float vertical = y * camera.z - point.z * camera.w;
        float depth = y * camera.w + point.z * camera.z;
        gl_Position = vec4(x * scale.x, -.12 - vertical * scale.y, -depth / extent, 1.0);
        uv = vec2(point.x, -point.y) / extent + .5;
        light = shade;
        elevation = point.z / 3.0 + referenceElevation;
      }`;
    const fragment = `#version 300 es
      precision mediump float;
      uniform sampler2D photo;
      uniform vec2 elevationRange;
      uniform float reliefMix;
      in vec2 uv;
      in float light;
      in float elevation;
      out vec4 color;
      void main() {
        vec3 satellite = pow(texture(photo, uv).rgb, vec3(.80));
        float normalized = clamp((elevation - elevationRange.x) / elevationRange.y, 0.0, 1.0);
        vec3 relief = mix(vec3(.16, .37, .37), vec3(.82, .77, .60), normalized);
        float contour = elevation / 10.0;
        float width = clamp(fwidth(contour), .003, .18);
        float line = 1.0 - smoothstep(0.0, width, abs(fract(contour + .5) - .5));
        relief *= 1.0 - .36 * line;
        color = vec4(mix(satellite, relief, reliefMix) * light, 1.0);
      }`;
    const compile = (kind, source) => {
      const shader = gl.createShader(kind);
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw Error(gl.getShaderInfoLog(shader));
      return shader;
    };
    const program = gl.createProgram();
    gl.attachShader(program, compile(gl.VERTEX_SHADER, vertex));
    gl.attachShader(program, compile(gl.FRAGMENT_SHADER, fragment));
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw Error(gl.getProgramInfoLog(program));
    gl.useProgram(program);
    this.cameraUniform = gl.getUniformLocation(program, 'camera');
    this.scaleUniform = gl.getUniformLocation(program, 'scale');
    this.reliefMixUniform = gl.getUniformLocation(program, 'reliefMix');
    gl.uniform1f(gl.getUniformLocation(program, 'extent'), this.extent);
    gl.uniform1f(gl.getUniformLocation(program, 'referenceElevation'), this.elevation);
    gl.uniform2fv(gl.getUniformLocation(program, 'elevationRange'), this.elevationRange);
    const vertices = new Float32Array(this.faces.length * 12);
    let offset = 0;
    for (const face of this.faces) for (const i of face.indices) {
      vertices.set(this.points[i], offset);
      vertices[offset + 3] = face.shade;
      offset += 4;
    }
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER, vertices, gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 16, 0);
    gl.enableVertexAttribArray(1);
    gl.vertexAttribPointer(1, 1, gl.FLOAT, false, 16, 12);
    gl.bindTexture(gl.TEXTURE_2D, gl.createTexture());
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, image);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
    gl.generateMipmap(gl.TEXTURE_2D);
    gl.enable(gl.DEPTH_TEST);
    if (gl.getError() !== gl.NO_ERROR) throw Error('No se pudo cargar la textura en WebGL.');
  }

  bindCamera(panel) {
    let drag;
    this.canvas.addEventListener('pointerdown', event => {
      if (event.button !== 0) return;
      drag = [event.clientX, event.clientY];
      this.canvas.setPointerCapture(event.pointerId);
    });
    this.canvas.addEventListener('pointermove', event => {
      if (!drag) return;
      this.yaw += (event.clientX - drag[0]) * .008;
      this.pitch = Math.max(.28, Math.min(1.35, this.pitch + (event.clientY - drag[1]) * .006));
      drag = [event.clientX, event.clientY];
      this.scheduleDraw();
    });
    this.canvas.addEventListener('lostpointercapture', () => { drag = null; });
    this.canvas.addEventListener('wheel', event => {
      event.preventDefault();
      this.zoomBy(Math.exp(-event.deltaY * .001));
    }, {passive: false});
    panel.querySelector('#terrain-zoom-in').addEventListener('click', () => this.zoomBy(1.3));
    panel.querySelector('#terrain-zoom-out').addEventListener('click', () => this.zoomBy(1 / 1.3));
    panel.querySelector('#terrain-reset').addEventListener('click', () => this.reset());
    this.layer.addEventListener('change', () => this.scheduleDraw());
  }

  zoomBy(factor) {
    this.zoom = Math.max(.6, Math.min(24, this.zoom * factor));
    this.scheduleDraw();
  }

  reset() {
    this.yaw = -.60;
    this.pitch = .66;
    this.zoom = 1;
    this.scheduleDraw();
  }

  scheduleDraw() {
    if (this.pending) return;
    this.pending = requestAnimationFrame(() => {
      this.pending = null;
      this.draw();
    });
  }

  draw() {
    const {w, h, dpr} = sizeCanvas(this.canvas);
    if (!w || !h) return;
    const scale = Math.min(w * .68, h * .80) * this.zoom / this.extent;
    // Adaptar la vista al tamaño en pantalla de un píxel nominal de Sentinel-2.
    let reliefMix = 1;
    if (this.hasImage && this.layer.value === 'satellite') reliefMix = 0;
    if (this.hasImage && this.layer.value === 'auto') reliefMix = Math.max(0, Math.min(1, (10 * scale - 1.5) / 2.5));
    this.imageryCredit.classList.toggle('hidden', reliefMix === 1);
    const layerText = reliefMix === 0 ? 'Vista satelital · Sentinel-2 de 2016'
      : reliefMix === 1 ? 'Vista de relieve · Copernicus DEM' : 'Vista mixta · Satélite y relieve';
    if (this.layerStatus.textContent !== layerText) this.layerStatus.textContent = layerText;
    const cos = Math.cos(this.yaw), sin = Math.sin(this.yaw);
    const pitchSin = Math.sin(this.pitch), pitchCos = Math.cos(this.pitch);
    const distance = [10000, 5000, 2000, 1000, 500, 200, 100, 50].find(m => m * scale <= 112) ?? 50;
    const scaleText = distance >= 1000 ? `${distance / 1000} km` : `${distance} m`;
    this.scaleBar.style.width = `${distance * scale}px`;
    this.scaleBar.nextElementSibling.textContent = scaleText;
    this.zoomLabel.textContent = `${num(this.zoom, 1)}×`;
    this.north.style.transform = `rotate(${Math.atan2(cos * pitchSin, -sin) + Math.PI / 2}rad)`;
    if (this.gl) {
      const gl = this.gl;
      gl.viewport(0, 0, this.canvas.width, this.canvas.height);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      gl.uniform4f(this.cameraUniform, cos, sin, pitchSin, pitchCos);
      gl.uniform2f(this.scaleUniform, 2 * scale / w, 2 * scale / h);
      gl.uniform1f(this.reliefMixUniform, reliefMix);
      gl.drawArrays(gl.TRIANGLES, 0, this.faces.length * 3);
      return;
    }
    const projected = this.points.map(([x, y, z]) => {
      const depth = sin * x + cos * y;
      return [w / 2 + (cos * x - sin * y) * scale,
        h * .56 + (depth * pitchSin - z * pitchCos) * scale,
        depth * pitchCos + z * pitchSin];
    });
    for (const face of this.faces) {
      const [a, b, c] = face.indices;
      face.depth = projected[a][2] + projected[b][2] + projected[c][2];
    }
    this.faces.sort((a, b) => a.depth - b.depth);
    const ctx = this.context;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    for (const face of this.faces) {
      const [a, b, c] = face.indices;
      const pa = projected[a], pb = projected[b], pc = projected[c];
      if (Math.max(pa[0], pb[0], pc[0]) < 0 || Math.min(pa[0], pb[0], pc[0]) > w ||
          Math.max(pa[1], pb[1], pc[1]) < 0 || Math.min(pa[1], pb[1], pc[1]) > h) continue;
      ctx.beginPath();
      ctx.moveTo(projected[a][0], projected[a][1]);
      ctx.lineTo(projected[b][0], projected[b][1]);
      ctx.lineTo(projected[c][0], projected[c][1]);
      ctx.closePath();
      const color = face.photoColor.map((value, i) => Math.round(value + (face.reliefColor[i] - value) * reliefMix));
      ctx.fillStyle = ctx.strokeStyle = `rgb(${color.join(',')})`;
      ctx.lineWidth = .65;
      ctx.fill();
      ctx.stroke();
    }
  }
}
