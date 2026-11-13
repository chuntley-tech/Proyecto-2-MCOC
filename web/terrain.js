'use strict';

function terrainObjectFaces(vertices, faces, color) {
  return faces.map((indices, i) => {
    const points = indices.map(index => vertices[index]);
    const [a, b, c] = points;
    const [ux, uy, uz] = b.map((value, axis) => value - a[axis]);
    const [vx, vy, vz] = c.map((value, axis) => value - a[axis]);
    const normal = [uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx];
    const light = (normal[0] * -.4 + normal[1] * -.35 + normal[2] * .85) / Math.hypot(...normal);
    const shade = .83 + .17 * Math.abs(light);
    const base = typeof color === 'function' ? color(i) : color;
    return {points, color: `rgb(${base.map(channel => Math.round(channel * shade)).join(',')})`};
  });
}

// Las dimensiones están en metros. El lomo llega a 1,50 m y las patas parten en z = 0.
function terrainCow(east, north, ground, angle) {
  const cream = [242, 236, 216], black = [37, 34, 36], pink = [224, 161, 152];
  const surfaces = [];
  const cos = Math.cos(angle), sin = Math.sin(angle);
  const place = ([x, y, z]) => [east + x * cos - y * sin, north + x * sin + y * cos, ground + z];
  function solid(rings, color) {
    const sides = 8;
    const vertices = rings.flatMap(([x, y, z, width, height]) => Array.from({length:sides}, (_, i) => {
      const a = i * 2 * Math.PI / sides;
      return place([x, y + width * Math.cos(a), z + height * Math.sin(a)]);
    }));
    const faces = [Array.from({length:sides}, (_, i) => sides - 1 - i)];
    for (let j = 0; j < rings.length - 1; j++) for (let i = 0; i < sides; i++) {
      const a = j * sides + i, b = j * sides + (i + 1) % sides;
      faces.push([a, b, b + sides, a + sides]);
    }
    faces.push(Array.from({length:sides}, (_, i) => vertices.length - sides + i));
    surfaces.push(...terrainObjectFaces(vertices, faces, color));
  }
  solid([[-.94,0,1.08,.22,.25], [-.72,0,1.13,.39,.37], [-.2,0,1.13,.4,.37],
    [.35,0,1.11,.34,.36], [.72,0,1.15,.24,.31]],
  i => [2,3,7,8,11,12,16,17,22,23,27,28].includes(i) ? black : cream);
  solid([[.48,0,1.15,.24,.30], [.86,0,1.13,.18,.25], [1.03,0,1.20,.18,.24]], black);
  solid([[.93,0,1.22,.19,.22], [1.22,0,1.15,.19,.20], [1.37,0,1.04,.16,.12]], cream);
  solid([[1.23,0,1.04,.16,.12], [1.45,0,1.03,.16,.10]], pink);
  for (const side of [-1, 1]) {
    solid([[.89,side*.18,1.33,.10,.06], [1.08,side*.27,1.36,.12,.05]], black);
    for (const x of [-.65, .47]) {
      const y = side*.24;
      solid([[x-.075,y,.45,.075,.45], [x+.075,y,.45,.075,.45]], cream);
      solid([[x-.08,y,.07,.084,.07], [x+.095,y,.07,.084,.07]], black);
    }
  }
  solid([[-1.12,0,.64,.049,.09], [-1,0,.87,.033,.18], [-.9,0,1.12,.038,.09]], black);
  return surfaces;
}

// Proyección ortográfica de una malla de elevaciones en ejes este/norte.
class TerrainView {
  constructor(panel, terrain, image, foundation) {
    this.canvas = panel.querySelector('canvas');
    this.objectCanvas = panel.querySelector('.terrain-objects');
    this.objectContext = this.objectCanvas.getContext('2d');
    this.beacon = panel.querySelector('#terrain-beacon');
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
    this.samples = samples;
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
    this.foundationHeight = Math.max(...foundation.map(mesh => mesh.vertices_m.reduce((top, p) => Math.max(top, p[2]), 0)));
    const concrete = [[172,184,186], [200,208,206], [221,222,212]];
    this.objects = foundation.flatMap((mesh, i) => terrainObjectFaces(mesh.vertices_m, mesh.faces, concrete[i % concrete.length]));
    const radius = foundation.reduce((r, mesh) => mesh.vertices_m.reduce((a, p) => Math.max(a, Math.hypot(p[0], p[1])), r), 0);
    for (const [x, y, angle] of [[.90,-.43,.4],[.54,-.98,-.65],[-.93,-.58,.95]]) {
      const east = x * (radius + 2), north = y * (radius + 2);
      this.objects.push(...terrainCow(east, north, this.groundAt(east, north), angle));
    }
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

  groundAt(east, north) {
    const x = (east + this.extent / 2) / this.spacing;
    const y = (north + this.extent / 2) / this.spacing;
    const i = Math.floor(x), j = Math.floor(y), u = x - i, v = y - j;
    const a = j * this.samples + i;
    const z = index => this.points[index][2] / 3;
    return u >= v
      ? (1-u)*z(a) + (u-v)*z(a+1) + v*z(a+this.samples+1)
      : (1-v)*z(a) + u*z(a+this.samples+1) + (v-u)*z(a+this.samples);
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
      uniform float reliefScale;
      out vec2 uv;
      out float light;
      out float elevation;
      void main() {
        float x = camera.x * point.x - camera.y * point.y;
        float y = camera.y * point.x + camera.x * point.y;
        float z = point.z * reliefScale;
        float vertical = y * camera.z - z * camera.w;
        float depth = y * camera.w + z * camera.z;
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
    this.reliefScaleUniform = gl.getUniformLocation(program, 'reliefScale');
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
    panel.querySelector('#terrain-focus').addEventListener('click', () => {
      this.zoom = this.detailZoom();
      this.scheduleDraw();
    });
    panel.querySelector('#terrain-reset').addEventListener('click', () => this.reset());
    this.layer.addEventListener('change', () => this.scheduleDraw());
  }

  zoomBy(factor) {
    this.zoom = Math.max(.6, Math.min(this.detailZoom(), this.zoom * factor));
    this.scheduleDraw();
  }

  detailZoom() {
    const {width, height} = this.canvas.getBoundingClientRect();
    const base = Math.min(width * .68, height * .80) / this.extent;
    return base > 0 ? Math.max(24, Math.min(12, width / 34, height / 30) / base) : this.zoom;
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

  drawObjects(project, detail, w, h, dpr) {
    const canvas = this.objectCanvas, ctx = this.objectContext;
    if (canvas.width !== this.canvas.width || canvas.height !== this.canvas.height) {
      canvas.width = this.canvas.width;
      canvas.height = this.canvas.height;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    this.beacon.classList.toggle('is-close', detail);
    this.beacon.style.top = `${project(0, 0, detail ? this.foundationHeight : 0)[1]}px`;
    if (!detail) return;
    const faces = this.objects.map(({points, color}) => {
      const projected = points.map(point => project(...point));
      const depth = projected.reduce((sum, point) => sum + point[2], 0) / projected.length;
      return {projected, depth, color};
    });
    faces.sort((a, b) => a.depth - b.depth);
    for (const {projected, color} of faces) {
      ctx.beginPath();
      ctx.moveTo(projected[0][0], projected[0][1]);
      for (const [x, y] of projected.slice(1)) ctx.lineTo(x, y);
      ctx.closePath();
      ctx.fillStyle = ctx.strokeStyle = color;
      ctx.lineWidth = .45;
      ctx.fill();
      ctx.stroke();
    }
  }

  draw() {
    const {w, h, dpr} = sizeCanvas(this.canvas);
    if (!w || !h) return;
    this.zoom = Math.min(this.zoom, this.detailZoom());
    const scale = Math.min(w * .68, h * .80) * this.zoom / this.extent;
    const detail = scale >= 1.5;
    const reliefScale = detail ? 1 / 3 : 1;
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
    const project = (x, y, z) => {
      const depth = sin * x + cos * y;
      return [w / 2 + (cos * x - sin * y) * scale,
        h * .56 + (depth * pitchSin - z * pitchCos) * scale,
        depth * pitchCos + z * pitchSin];
    };
    const distance = [10000, 5000, 2000, 1000, 500, 200, 100, 50, 20, 10, 5, 2].find(m => m * scale <= 112) ?? 2;
    const scaleText = distance >= 1000 ? `${distance / 1000} km` : `${distance} m`;
    this.scaleBar.style.width = `${distance * scale}px`;
    this.scaleBar.nextElementSibling.textContent = scaleText;
    this.zoomLabel.textContent = `${num(this.zoom, 1)}×`;
    this.north.style.transform = `rotate(${Math.atan2(cos * pitchSin, -sin) + Math.PI / 2}rad)`;
    this.drawObjects(project, detail, w, h, dpr);
    if (this.gl) {
      const gl = this.gl;
      gl.viewport(0, 0, this.canvas.width, this.canvas.height);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      gl.uniform4f(this.cameraUniform, cos, sin, pitchSin, pitchCos);
      gl.uniform2f(this.scaleUniform, 2 * scale / w, 2 * scale / h);
      gl.uniform1f(this.reliefMixUniform, reliefMix);
      gl.uniform1f(this.reliefScaleUniform, reliefScale);
      gl.drawArrays(gl.TRIANGLES, 0, this.faces.length * 3);
      return;
    }
    const projected = this.points.map(([x, y, z]) => project(x, y, z * reliefScale));
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
