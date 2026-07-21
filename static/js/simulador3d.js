import * as THREE from 'three';

// --- Simulación 3D de vuelo AEROVEX ---
// Escena cinematográfica: terreno montañoso procedural, nubes, pistas en
// cada nodo de la ruta y un avión con logo AEROVEX que despega, cruza y
// aterriza en cada tramo del itinerario calculado por Dijkstra.

const SEG = 420;          // longitud (unidades three.js) de cada tramo de vuelo
const CRUISE_ALT = 95;    // altitud de crucero
const DURACION_TRAMO = 16; // segundos por tramo

let renderer, scene, camera, clock, avionGrupo, nubesGrupo, terrenoMesh;
let overlayEl, viewportEl, hudEls = {};
let legs = [];
let tGlobal = 0;
let tiempoOlas = 0;
let playing = false;
let animId = null;
const camaraLookAt = new THREE.Vector3();

function easeInOutQuad(x) { return x < 0.5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2; }
function smoothstep(edge0, edge1, x) {
    const t = Math.min(1, Math.max(0, (x - edge0) / (edge1 - edge0)));
    return t * t * (3 - 2 * t);
}
function ruido2D(x, z, seed) {
    return Math.sin(x * 0.015 + seed) * Math.cos(z * 0.02 + seed * 1.3) * 0.5
         + Math.sin(x * 0.045 + seed * 2.1) * Math.cos(z * 0.05 + seed) * 0.25
         + Math.sin(x * 0.09 + seed * 3.7) * 0.15;
}

function textoTextura(texto, opts = {}) {
    const cv = document.createElement('canvas');
    cv.width = opts.w || 512; cv.height = opts.h || 128;
    const ctx = cv.getContext('2d');
    if (opts.bg) { ctx.fillStyle = opts.bg; ctx.fillRect(0, 0, cv.width, cv.height); }
    ctx.fillStyle = opts.color || '#0a0e1a';
    ctx.font = (opts.weight || '700') + ' ' + (opts.size || 70) + 'px Arial, sans-serif';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(texto, cv.width / 2, cv.height / 2);
    const tex = new THREE.CanvasTexture(cv);
    tex.needsUpdate = true;
    return tex;
}

function texturaPista(codigo) {
    // Lienzo APAISADO: el eje largo (X del canvas) debe coincidir con el eje
    // largo de la geometría de la pista (world X = dirección de vuelo). Antes
    // este canvas era vertical y la geometría quedaba girada 90° respecto al
    // rumbo del avión, por eso la pista se veía "cruzada" al despegar/aterrizar.
    const cv = document.createElement('canvas');
    cv.width = 1024; cv.height = 256;
    const ctx = cv.getContext('2d');
    ctx.fillStyle = '#2b2f36'; ctx.fillRect(0, 0, cv.width, cv.height);
    ctx.strokeStyle = '#e8e8e8'; ctx.lineWidth = 10;
    ctx.setLineDash([40, 28]);
    ctx.beginPath(); ctx.moveTo(20, cv.height / 2); ctx.lineTo(cv.width - 20, cv.height / 2); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = '#e8e8e8';
    for (let i = 0; i < 6; i++) {
        ctx.fillRect(40, 30 + i * 10, 60, 6); ctx.fillRect(40, cv.height - 30 - i * 10 - 6, 60, 6);
        ctx.fillRect(cv.width - 100, 30 + i * 10, 60, 6); ctx.fillRect(cv.width - 100, cv.height - 30 - i * 10 - 6, 60, 6);
    }
    ctx.fillStyle = '#22d3ee'; ctx.font = '700 90px Arial'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(codigo, cv.width / 2, cv.height * 0.28);
    return new THREE.CanvasTexture(cv);
}

function mezclarColor(a, b, t) {
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
}

// GPS (Galápagos) está a ~1000 km de mar abierto del continente: cualquier
// tramo que toque ese nodo se renderiza como océano, no como cordillera.
function esTramoOceanico(leg) {
    return leg.origen === 'GPS' || leg.destino === 'GPS';
}

function tipoTerrenoEnX(x) {
    let idx = Math.floor(x / SEG);
    if (idx < 0) idx = 0;
    if (idx > legs.length - 1) idx = legs.length - 1;
    return esTramoOceanico(legs[idx]) ? 'oceano' : 'tierra';
}

function crearTerreno(longitudTotal, seed) {
    const anchoZ = 900;
    const segX = Math.max(20, Math.floor(longitudTotal / 8));
    const segZ = 70;
    const geo = new THREE.PlaneGeometry(longitudTotal, anchoZ, segX, segZ);
    geo.rotateX(-Math.PI / 2);
    geo.translate(longitudTotal / 2 - 100, 0, 0);
    const pos = geo.attributes.position;
    const colors = [];
    const nodosX = legs.map((_, idx) => idx * SEG).concat([legs.length * SEG]);
    const oceanoIdx = [];
    for (let i = 0; i < pos.count; i++) {
        const x = pos.getX(i), z = pos.getZ(i);
        const distPista = Math.min(...nodosX.map(nx => Math.abs(x - nx)));
        const aplano = smoothstep(60, 5, distPista);
        const tipo = tipoTerrenoEnX(x);
        let h, color;
        if (tipo === 'oceano') {
            h = 0;
            const profundo = smoothstep(40, 240, distPista);
            color = mezclarColor([0.22, 0.62, 0.6], [0.04, 0.16, 0.34], profundo);
            oceanoIdx.push(i);
        } else {
            h = ruido2D(x, z, seed) * 55;
            h *= (1 - aplano);
            if (h < 0) h *= 0.3;
            if (h > 42) color = [0.85, 0.87, 0.9];
            else if (h > 26) color = [0.45, 0.42, 0.4];
            else if (h > 6) color = [0.28, 0.42, 0.24];
            else color = [0.18, 0.32, 0.18];
        }
        pos.setY(i, h);
        colors.push(...color);
    }
    geo.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
    geo.computeVertexNormals();
    const mat = new THREE.MeshStandardMaterial({ vertexColors: true, flatShading: true, roughness: 1 });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.receiveShadow = true;
    mesh.userData.oceanoIdx = oceanoIdx;
    return mesh;
}

function crearIslote(x, z, escala) {
    const grupo = new THREE.Group();
    const cono = new THREE.Mesh(
        new THREE.ConeGeometry(6 * escala, 5 * escala, 7),
        new THREE.MeshStandardMaterial({ color: 0x3f5a34, flatShading: true, roughness: 1 })
    );
    cono.position.y = 2.6 * escala;
    grupo.add(cono);
    const base = new THREE.Mesh(
        new THREE.CylinderGeometry(6.4 * escala, 7 * escala, 1.2, 7),
        new THREE.MeshStandardMaterial({ color: 0xd8c79a, roughness: 1 })
    );
    base.position.y = 0.2;
    grupo.add(base);
    grupo.position.set(x, 0, z);
    return grupo;
}

// Pequeño archipiélago decorativo alrededor de la pista de Galápagos, para
// reforzar que ese nodo está rodeado de mar y no de cordillera continental.
function crearArchipielago(x) {
    const grupo = new THREE.Group();
    const posiciones = [[-95, -150], [55, -195], [150, 95], [-45, 175], [225, 25]];
    posiciones.forEach(([dx, dz]) => grupo.add(crearIslote(x + dx, dz, 0.7 + Math.random() * 0.8)));
    return grupo;
}

function crearNube() {
    const grupo = new THREE.Group();
    const mat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 1, transparent: true, opacity: 0.85 });
    const puffs = 3 + Math.floor(Math.random() * 4);
    for (let i = 0; i < puffs; i++) {
        const geo = new THREE.IcosahedronGeometry(6 + Math.random() * 6, 0);
        const m = new THREE.Mesh(geo, mat);
        m.position.set((Math.random() - 0.5) * 22, (Math.random() - 0.5) * 6, (Math.random() - 0.5) * 14);
        m.scale.setScalar(0.7 + Math.random() * 0.6);
        grupo.add(m);
    }
    return grupo;
}

function crearNubes(longitudTotal, cantidad) {
    const grupo = new THREE.Group();
    for (let i = 0; i < cantidad; i++) {
        const nube = crearNube();
        nube.position.set(Math.random() * longitudTotal - 60, 100 + Math.random() * 55, (Math.random() - 0.5) * 700);
        nube.userData.velocidad = 2 + Math.random() * 3;
        grupo.add(nube);
    }
    return grupo;
}

function crearPista(x, codigo) {
    const tex = texturaPista(codigo);
    // Largo (130) en X = dirección de vuelo; ancho (26) en Z, para que quede
    // alineada con el eje sobre el que se mueve el avión.
    const geo = new THREE.PlaneGeometry(130, 26);
    geo.rotateX(-Math.PI / 2);
    const mat = new THREE.MeshStandardMaterial({ map: tex, roughness: 0.9 });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.set(x, 0.15, 0);
    mesh.receiveShadow = true;
    return mesh;
}

function crearAvion() {
    const g = new THREE.Group();
    const matFuselaje = new THREE.MeshStandardMaterial({ color: 0xe7ecf5, roughness: 0.4, metalness: 0.3 });
    const matAcento = new THREE.MeshStandardMaterial({ color: 0x22d3ee, roughness: 0.35, metalness: 0.4 });
    const matMotor = new THREE.MeshStandardMaterial({ color: 0x1e293b, roughness: 0.6 });

    const fuselaje = new THREE.Mesh(new THREE.CapsuleGeometry(2.6, 20, 6, 12), matFuselaje);
    fuselaje.rotation.z = Math.PI / 2;
    fuselaje.castShadow = true;
    g.add(fuselaje);

    const ala = new THREE.Mesh(new THREE.BoxGeometry(6, 0.4, 22), matFuselaje);
    ala.position.set(-1, -0.3, 0);
    ala.castShadow = true;
    g.add(ala);

    const colaVert = new THREE.Mesh(new THREE.BoxGeometry(0.4, 5, 3.5), matAcento);
    colaVert.position.set(-9.5, 3.2, 0);
    g.add(colaVert);

    const colaHoriz = new THREE.Mesh(new THREE.BoxGeometry(0.3, 0.3, 8), matFuselaje);
    colaHoriz.position.set(-9.3, 1.2, 0);
    g.add(colaHoriz);

    [-5, 5].forEach(zPos => {
        const motor = new THREE.Mesh(new THREE.CylinderGeometry(1, 1, 4, 10), matMotor);
        motor.rotation.z = Math.PI / 2;
        motor.position.set(-1, -2.4, zPos);
        g.add(motor);
    });

    const logoTex = textoTextura('AEROVEX', { bg: null, color: '#0e2a33', size: 60, w: 512, h: 128 });
    const logoMat = new THREE.MeshBasicMaterial({ map: logoTex, transparent: true });
    [1, -1].forEach(lado => {
        const logo = new THREE.Mesh(new THREE.PlaneGeometry(9, 2.2), logoMat);
        logo.position.set(1, 1.1, lado * 2.65);
        logo.rotation.y = lado > 0 ? Math.PI / 2 : -Math.PI / 2;
        g.add(logo);
    });

    return g;
}

function crearCielo() {
    const geo = new THREE.SphereGeometry(1400, 24, 16);
    const mat = new THREE.ShaderMaterial({
        side: THREE.BackSide,
        uniforms: {
            colorCielo: { value: new THREE.Color(0x4fb2e0) },
            colorHorizonte: { value: new THREE.Color(0xbfe3f0) }
        },
        vertexShader: `varying vec3 vPos; void main(){ vPos = position; gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0); }`,
        fragmentShader: `
            varying vec3 vPos; uniform vec3 colorCielo; uniform vec3 colorHorizonte;
            void main(){
                float h = normalize(vPos).y;
                float t = smoothstep(-0.05, 0.5, h);
                gl_FragColor = vec4(mix(colorHorizonte, colorCielo, t), 1.0);
            }`
    });
    return new THREE.Mesh(geo, mat);
}

function limpiarEscena() {
    if (animId) cancelAnimationFrame(animId);
    animId = null;
    if (scene) {
        scene.traverse(obj => {
            if (obj.geometry) obj.geometry.dispose();
            if (obj.material) {
                const mats = Array.isArray(obj.material) ? obj.material : [obj.material];
                mats.forEach(m => { if (m.map) m.map.dispose(); m.dispose(); });
            }
        });
    }
    if (renderer) {
        renderer.dispose();
        if (renderer.domElement && renderer.domElement.parentNode) {
            renderer.domElement.parentNode.removeChild(renderer.domElement);
        }
    }
    scene = null; renderer = null; terrenoMesh = null; tiempoOlas = 0;
}

function crearEscena(container) {
    scene = new THREE.Scene();
    const totalLength = legs.length * SEG + 200;

    scene.add(crearCielo());
    scene.fog = new THREE.Fog(0xbfe3f0, 260, 1100);

    scene.add(new THREE.HemisphereLight(0xffffff, 0x445533, 0.9));
    const sol = new THREE.DirectionalLight(0xfff4dd, 1.1);
    sol.position.set(-200, 320, 140);
    sol.castShadow = true;
    sol.shadow.mapSize.set(1024, 1024);
    sol.shadow.camera.left = -300; sol.shadow.camera.right = 300;
    sol.shadow.camera.top = 300; sol.shadow.camera.bottom = -300;
    sol.shadow.camera.far = 900;
    scene.add(sol);

    terrenoMesh = crearTerreno(totalLength, 7.3);
    scene.add(terrenoMesh);

    legs.forEach((leg, i) => {
        scene.add(crearPista(i * SEG, leg.origen));
        if (leg.origen === 'GPS') scene.add(crearArchipielago(i * SEG));
    });
    const ultimoDestino = legs[legs.length - 1].destino;
    scene.add(crearPista(legs.length * SEG, ultimoDestino));
    if (ultimoDestino === 'GPS') scene.add(crearArchipielago(legs.length * SEG));

    nubesGrupo = crearNubes(totalLength, Math.max(18, legs.length * 10));
    scene.add(nubesGrupo);

    avionGrupo = crearAvion();
    scene.add(avionGrupo);

    camera = new THREE.PerspectiveCamera(55, container.clientWidth / container.clientHeight, 0.5, 2000);

    renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(container.clientWidth, container.clientHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;
    container.innerHTML = '';
    container.appendChild(renderer.domElement);
}

function calcularEstadoVuelo(t) {
    let i = Math.min(Math.floor(t), legs.length - 1);
    let f = t - i;
    if (t >= legs.length) { i = legs.length - 1; f = 1; }

    const xBase = i * SEG;
    let alt, pitch = 0, fase;

    if (f < 0.07) { fase = 'DESPEGUE'; const p = f / 0.07; alt = Math.pow(p, 1.6) * 4; pitch = p * 0.12; }
    else if (f < 0.24) { fase = 'ASCENSO'; const p = (f - 0.07) / 0.17; alt = 4 + easeInOutQuad(p) * (CRUISE_ALT - 4); pitch = 0.12 + p * 0.10; }
    else if (f < 0.76) { fase = 'CRUCERO'; alt = CRUISE_ALT + Math.sin(f * 40) * 0.6; pitch = 0.02; }
    else if (f < 0.93) { fase = 'DESCENSO'; const p = (f - 0.76) / 0.17; alt = CRUISE_ALT - easeInOutQuad(p) * (CRUISE_ALT - 4); pitch = -0.10; }
    else { fase = 'ATERRIZAJE'; const p = (f - 0.93) / 0.07; alt = 4 * (1 - Math.pow(p, 1.5)); pitch = -0.05 * (1 - p); }

    const x = xBase + f * SEG;
    const z = Math.sin(f * Math.PI) * (legs.length > 1 ? 10 : 6) * (i % 2 === 0 ? 1 : -1);

    return { x, y: alt, z, pitch, fase, legIndex: i, legFrac: f };
}

function actualizarHUD(st) {
    const leg = legs[st.legIndex];
    if (hudEls.fase) hudEls.fase.textContent = st.fase;
    if (hudEls.ruta) hudEls.ruta.textContent = leg.origen + ' ➔ ' + leg.destino;
    if (hudEls.alt) hudEls.alt.textContent = Math.round(st.y * 38) + ' m';
    if (hudEls.vel) hudEls.vel.textContent = (st.fase === 'CRUCERO' ? 830 : Math.round(200 + st.y * 6)) + ' km/h';
    if (hudEls.tramo) hudEls.tramo.textContent = 'Tramo ' + (st.legIndex + 1) + ' / ' + legs.length;
    if (hudEls.progreso) hudEls.progreso.style.width = Math.min(100, (tGlobal / legs.length) * 100) + '%';
    if (leg.climaAdverso && hudEls.clima) hudEls.clima.style.display = 'inline-flex';
    else if (hudEls.clima) hudEls.clima.style.display = 'none';
}

function onVueloFinalizado() {
    if (hudEls.fase) hudEls.fase.textContent = 'ATERRIZADO';
    if (hudEls.finPanel) hudEls.finPanel.style.display = 'flex';
}

function animar() {
    animId = requestAnimationFrame(animar);
    const dt = Math.min(clock.getDelta(), 0.05);
    if (playing) {
        tGlobal += dt / DURACION_TRAMO;
        if (tGlobal >= legs.length) { tGlobal = legs.length; playing = false; onVueloFinalizado(); }
    }
    const st = calcularEstadoVuelo(tGlobal);

    avionGrupo.position.set(st.x, st.y + 2, st.z);
    avionGrupo.rotation.set(-st.z * 0.01, 0, st.pitch);

    const detras = 34, altura = 12 + st.y * 0.15;
    const camObjetivo = new THREE.Vector3(st.x - detras, st.y + altura, st.z + 14);
    camera.position.lerp(camObjetivo, 1 - Math.pow(0.001, dt));
    const mirar = new THREE.Vector3(st.x + 24, st.y + 3, st.z);
    camaraLookAt.lerp(mirar, 1 - Math.pow(0.0005, dt));
    camera.lookAt(camaraLookAt);

    if (nubesGrupo) {
        const totalLength = legs.length * SEG + 200;
        nubesGrupo.children.forEach(n => {
            n.position.x += n.userData.velocidad * dt;
            if (n.position.x > totalLength + 60) n.position.x -= (totalLength + 120);
        });
    }

    if (terrenoMesh && terrenoMesh.userData.oceanoIdx && terrenoMesh.userData.oceanoIdx.length) {
        tiempoOlas += dt;
        const posAttr = terrenoMesh.geometry.attributes.position;
        const idxs = terrenoMesh.userData.oceanoIdx;
        for (let k = 0; k < idxs.length; k++) {
            const vi = idxs[k];
            const x = posAttr.getX(vi), z = posAttr.getZ(vi);
            const ola = Math.sin(x * 0.05 + tiempoOlas * 1.6) * Math.cos(z * 0.06 + tiempoOlas * 1.1) * 1.4;
            posAttr.setY(vi, ola);
        }
        posAttr.needsUpdate = true;
    }

    actualizarHUD(st);
    renderer.render(scene, camera);
}

function construirHUD() {
    hudEls = {
        fase: document.getElementById('sim3d-fase'),
        ruta: document.getElementById('sim3d-ruta'),
        alt: document.getElementById('sim3d-alt'),
        vel: document.getElementById('sim3d-vel'),
        tramo: document.getElementById('sim3d-tramo'),
        progreso: document.getElementById('sim3d-progreso'),
        clima: document.getElementById('sim3d-clima'),
        finPanel: document.getElementById('sim3d-fin')
    };
}

function onResize() {
    if (!renderer || !camera || !viewportEl) return;
    camera.aspect = viewportEl.clientWidth / viewportEl.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(viewportEl.clientWidth, viewportEl.clientHeight);
}

function iniciarSimulacion3D(rutaDatos, criterio) {
    if (!rutaDatos || rutaDatos.length < 2) return;
    overlayEl = document.getElementById('sim3d-overlay');
    viewportEl = document.getElementById('sim3d-viewport');
    if (!overlayEl || !viewportEl) return;

    legs = [];
    for (let i = 0; i < rutaDatos.length - 1; i++) {
        legs.push({
            origen: rutaDatos[i].info,
            destino: rutaDatos[i + 1].info,
            climaAdverso: !!rutaDatos[i + 1].clima
        });
    }

    limpiarEscena();
    construirHUD();
    overlayEl.style.display = 'flex';
    if (hudEls.finPanel) hudEls.finPanel.style.display = 'none';
    const criterioEl = document.getElementById('sim3d-criterio');
    if (criterioEl) criterioEl.textContent = criterio || '';

    crearEscena(viewportEl);
    clock = new THREE.Clock();
    tGlobal = 0;
    playing = true;
    window.addEventListener('resize', onResize);
    onResize();
    animar();
}

function repetirSimulacion3D() {
    tGlobal = 0;
    playing = true;
    if (hudEls.finPanel) hudEls.finPanel.style.display = 'none';
}

function cerrarSimulacion3D() {
    playing = false;
    window.removeEventListener('resize', onResize);
    limpiarEscena();
    if (overlayEl) overlayEl.style.display = 'none';
}

window.addEventListener('keydown', e => {
    if (e.key === 'Escape' && overlayEl && overlayEl.style.display === 'flex') cerrarSimulacion3D();
});

window.iniciarSimulacion3D = iniciarSimulacion3D;
window.repetirSimulacion3D = repetirSimulacion3D;
window.cerrarSimulacion3D = cerrarSimulacion3D;
window.dispatchEvent(new Event('aerovex3d-ready'));
