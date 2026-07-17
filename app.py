import json
import heapq
from flask import Flask, render_template, request, redirect, url_for
from config import Config
from models import db, Aeropuerto, Ruta, Simulacion

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

# Factor de penalización por clima adverso: afecta TIEMPO, COSTO y CONSUMO
# (una tormenta obliga a reducir velocidad, esperar en espera/holding y consumir
# más combustible), pero NO la distancia física de la ruta, que no cambia.
FACTOR_CLIMA_ADVERSO = 1.5

# --- ALGORITMO DE DIJKSTRA (INVESTIGACIÓN DE OPERACIONES) ---
def dijkstra(origen_id, destino_id, criterio):
    aeropuertos = Aeropuerto.query.filter_by(estado="Abierto").all()
    ids_abiertos = {a.id for a in aeropuertos}

    if origen_id not in ids_abiertos or destino_id not in ids_abiertos:
        return None, None, "Alerta: El aeropuerto de origen o destino se encuentra cerrado."

    rutas_bd = Ruta.query.filter(Ruta.estado != "Inhabilitada").all()
    grafo = {a.id: [] for a in aeropuertos}

    for ruta in rutas_bd:
        if ruta.origen_id in ids_abiertos and ruta.destino_id in ids_abiertos:
            # Penalización por evento dinámico: +50% al peso si hay Clima Adverso.
            # Se aplica solo para decidir el camino; el impacto real en los
            # totales mostrados se calcula después, sobre la ruta ya elegida.
            penalizacion = FACTOR_CLIMA_ADVERSO if ruta.estado == "Clima Adverso" else 1.0

            if "Distancia" in criterio: peso = ruta.distancia * penalizacion
            elif "Tiempo" in criterio: peso = ruta.tiempo * penalizacion
            else: peso = ruta.costo * penalizacion

            grafo[ruta.origen_id].append((ruta.destino_id, peso, ruta))

    distancias = {nodo: float('inf') for nodo in grafo}
    distancias[origen_id] = 0
    padres = {nodo: None for nodo in grafo}
    rutas_usadas = {nodo: None for nodo in grafo}
    pq = [(0, origen_id)]

    while pq:
        dist_actual, nodo_actual = heapq.heappop(pq)
        if dist_actual > distancias[nodo_actual]: continue
        if nodo_actual == destino_id: break

        for vecino, peso, ruta_obj in grafo[nodo_actual]:
            nueva_distancia = dist_actual + peso
            if nueva_distancia < distancias[vecino]:
                distancias[vecino] = nueva_distancia
                padres[vecino] = nodo_actual
                rutas_usadas[vecino] = ruta_obj
                heapq.heappush(pq, (nueva_distancia, vecino))

    if distancias[destino_id] == float('inf'):
        return None, None, "Alerta: No existe una ruta viable por cortes en la red o aeropuertos cerrados."

    camino_nodos = []
    rutas_camino = []
    nodo_temp = destino_id
    clima_adverso = False

    while nodo_temp is not None:
        camino_nodos.insert(0, nodo_temp)
        ruta_padre = rutas_usadas[nodo_temp]
        if ruta_padre:
            rutas_camino.insert(0, ruta_padre)
            if ruta_padre.estado == "Clima Adverso":
                clima_adverso = True
        nodo_temp = padres[nodo_temp]

    msj = "Ruta óptima calculada exitosamente. Condiciones climáticas normales."
    if clima_adverso:
        msj = "Precaución: la ruta atraviesa zonas con Clima Adverso. Tiempo, costo y combustible penalizados +50% en esos tramos."

    return camino_nodos, rutas_camino, msj


def calcular_totales(rutas_opt):
    """Calcula los totales reales de la ruta ya elegida, aplicando la
    penalización de Clima Adverso a tiempo/costo/consumo (no a distancia),
    tramo por tramo -- así el efecto de la restricción SÍ se ve en el resultado.
    También devuelve los totales SIN penalizar, para poder mostrar cuánto
    cambió exactamente por causa del clima (delta)."""
    dist_total = tiempo_total = costo_total = consumo_total = 0.0
    tiempo_base = costo_base = consumo_base = 0.0
    for r in rutas_opt:
        pen = FACTOR_CLIMA_ADVERSO if r.estado == "Clima Adverso" else 1.0
        dist_total += r.distancia
        tiempo_total += r.tiempo * pen
        costo_total += r.costo * pen
        consumo_total += r.consumo * pen
        tiempo_base += r.tiempo
        costo_base += r.costo
        consumo_base += r.consumo
    return (round(dist_total, 1), round(tiempo_total, 1), round(costo_total, 2), round(consumo_total, 1),
            round(tiempo_base, 1), round(costo_base, 2), round(consumo_base, 1))


# --- RUTAS DE FLASK ---
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/dashboard")
def dashboard():
    total_simulaciones = Simulacion.query.count()
    total_rutas = Ruta.query.count()
    aeropuertos_activos = Aeropuerto.query.filter_by(estado="Abierto").count()

    simulaciones = Simulacion.query.all()
    criterios_stats = {"Menor Distancia": 0, "Menor Tiempo": 0, "Menor Costo": 0}
    for sim in simulaciones:
        if sim.criterio in criterios_stats:
            criterios_stats[sim.criterio] += 1

    return render_template("dashboard.html",
                           total_sim=total_simulaciones,
                           total_rutas=total_rutas,
                           nodos=aeropuertos_activos,
                           grafico_criterios=json.dumps(criterios_stats),
                           ultimas_sim=Simulacion.query.order_by(Simulacion.id.desc()).limit(5).all())

@app.route("/aeropuertos", methods=["GET", "POST"])
def aeropuertos():
    if request.method == "POST":
        cod = request.form.get("codigo", "").upper().strip()
        nom = request.form.get("nombre", "").upper().strip()
        ciu = request.form.get("ciudad", "").strip()
        if cod and nom and ciu:
            nuevo = Aeropuerto(codigo=cod, nombre=nom, ciudad=ciu, latitud=-0.2201, longitud=-78.5123)
            try:
                db.session.add(nuevo)
                db.session.commit()
            except Exception:
                db.session.rollback()
        return redirect(url_for("aeropuertos"))

    lista_aero = Aeropuerto.query.all()
    lista_rutas = Ruta.query.all()
    rutas_unicas = [r for r in lista_rutas if r.origen_id < r.destino_id]

    return render_template("aeropuertos.html", aeropuertos=lista_aero, rutas=rutas_unicas)

@app.route("/toggle_aeropuerto/<int:id>")
def toggle_aeropuerto(id):
    a = Aeropuerto.query.get_or_404(id)
    a.estado = "Cerrado" if a.estado == "Abierto" else "Abierto"
    db.session.commit()
    return redirect(url_for('aeropuertos'))

@app.route("/estado_ruta/<int:id>", methods=["POST"])
def estado_ruta(id):
    r1 = Ruta.query.get_or_404(id)
    nuevo_estado = request.form.get("estado")
    r1.estado = nuevo_estado
    r2 = Ruta.query.filter_by(origen_id=r1.destino_id, destino_id=r1.origen_id).first()
    if r2: r2.estado = nuevo_estado
    db.session.commit()
    return redirect(url_for('aeropuertos'))

@app.route("/rutas", methods=["GET", "POST"])
def rutas():
    aeropuertos = Aeropuerto.query.all()
    simulaciones = Simulacion.query.order_by(Simulacion.id.desc()).limit(15).all()

    origen_sel = None
    destino_sel = None
    criterio_sel = "Menor Distancia"

    if request.method == "POST":
        origen_sel = int(request.form.get("origen"))
        destino_sel = int(request.form.get("destino"))
        criterio_sel = request.form.get("criterio")

        if origen_sel == destino_sel:
            return render_template("rutas.html", aeropuertos=aeropuertos, simulaciones=simulaciones,
                                   error="El origen y destino no pueden ser el mismo.",
                                   origen_sel=origen_sel, destino_sel=destino_sel, criterio_sel=criterio_sel)

        nodos, rutas_opt, msj = dijkstra(origen_sel, destino_sel, criterio_sel)

        if nodos:
            dist_total, tiempo_total, costo_total, consumo_total, tiempo_base, costo_base, consumo_base = calcular_totales(rutas_opt)
            hay_clima_adverso = any(r.estado == "Clima Adverso" for r in rutas_opt)
            delta_tiempo = round(tiempo_total - tiempo_base, 1)
            delta_costo = round(costo_total - costo_base, 2)
            delta_consumo = round(consumo_total - consumo_base, 1)
            escalas = max(len(nodos) - 2, 0)

            origen_obj = Aeropuerto.query.get(origen_sel)
            destino_obj = Aeropuerto.query.get(destino_sel)
            nombres_ruta = " ➔ ".join([Aeropuerto.query.get(n).codigo for n in nodos])

            coordenadas = [{"lat": Aeropuerto.query.get(n).latitud, "lon": Aeropuerto.query.get(n).longitud,
                            "info": Aeropuerto.query.get(n).codigo,
                            "clima": (rutas_opt[i - 1].estado == "Clima Adverso") if i > 0 else False}
                           for i, n in enumerate(nodos)]

            sim = Simulacion(origen=f"{origen_obj.ciudad} ({origen_obj.codigo})", destino=f"{destino_obj.ciudad} ({destino_obj.codigo})",
                             criterio=criterio_sel, distancia_total=dist_total, tiempo_total=tiempo_total,
                             costo_total=costo_total, consumo_total=consumo_total, nodos_ruta=nombres_ruta, estado_red=msj)
            db.session.add(sim)
            db.session.commit()

            simulaciones = Simulacion.query.order_by(Simulacion.id.desc()).limit(15).all()
            return render_template("rutas.html", aeropuertos=aeropuertos, simulaciones=simulaciones,
                                   mapa_ruta=json.dumps(coordenadas), error=msj if "Alerta" in msj else None, detalle=sim,
                                   escalas=escalas, hay_clima_adverso=hay_clima_adverso,
                                   delta_tiempo=delta_tiempo, delta_costo=delta_costo, delta_consumo=delta_consumo,
                                   origen_sel=origen_sel, destino_sel=destino_sel, criterio_sel=criterio_sel)
        else:
            return render_template("rutas.html", aeropuertos=aeropuertos, simulaciones=simulaciones, error=msj,
                                   origen_sel=origen_sel, destino_sel=destino_sel, criterio_sel=criterio_sel)

    return render_template("rutas.html", aeropuertos=aeropuertos, simulaciones=simulaciones, mapa_ruta="[]",
                           origen_sel=origen_sel, destino_sel=destino_sel, criterio_sel=criterio_sel)


def inicializar_bd():
    # Aeropuertos: se crean solo si no existen (por código), nunca se sobreescriben.
    datos_aeropuertos = [
        ("UIO", "MARISCAL SUCRE", "Quito", -0.1234, -78.3565),
        ("GYE", "JOSÉ JOAQUÍN DE OLMEDO", "Guayaquil", -2.1574, -79.8835),
        ("CUE", "MARISCAL LAMAR", "Cuenca", -2.9001, -79.0045),
        ("GPS", "SEYMOUR BALTRA", "Galápagos", -0.4491, -90.2833),
        ("MEC", "ELOY ALFARO", "Manta", -0.9474, -80.6781),
    ]
    for cod, nom, ciu, lat, lon in datos_aeropuertos:
        if not Aeropuerto.query.filter_by(codigo=cod).first():
            db.session.add(Aeropuerto(codigo=cod, nombre=nom, ciudad=ciu, latitud=lat, longitud=lon))
    db.session.commit()

    # Rutas: distancia/tiempo/costo/consumo verificados con datos reales de vuelo
    # entre aeropuertos ecuatorianos (fuentes: flightconnections, kiwi, momondo,
    # trip.com, jul-2026). Costo y consumo con un modelo costo = base +
    # tarifa_km*distancia + tarifa_min*tiempo, calibrado para una aeronave tipo
    # A320/A319 (la más usada en estas rutas domésticas).
    #
    # IMPORTANTE: esto se ejecuta en CADA arranque de la app (no solo la primera
    # vez), y actualiza estos valores aunque la ruta ya exista en la base de
    # datos -- así, si corriges estos números más adelante, se reflejan solos
    # sin tener que borrar la base de datos a mano. El "estado" (Activa/Clima
    # Adverso/Inhabilitada) de cada ruta NUNCA se toca aquí, para no perder lo
    # que hayas configurado desde Gestión de Red.
    datos_rutas = [
        ("UIO", "GYE", 282, 45, 90, 110),
        ("UIO", "CUE", 314, 55, 97, 130),
        ("UIO", "MEC", 258, 50, 88, 120),
        ("GYE", "CUE", 129, 35, 68, 92),
        ("GYE", "GPS", 1170, 115, 221, 244),
        ("MEC", "GYE", 165, 35, 72, 92),
        # UIO-GPS: en la realidad, todo vuelo Quito-Galápagos hace escala
        # técnica en Guayaquil sin cambio de avión (un solo itinerario/número
        # de vuelo, ~2h06-2h14 real). Se modela como arco propio porque es un
        # producto distinto a una conexión real con cambio de avión: más
        # rápido y más corto que ir UIO-GYE-GPS por separado, pero más caro
        # (tarifa premium + tasas de conservación de Galápagos). Esto es lo
        # que permite que "Menor Costo" prefiera la conexión vía Guayaquil
        # (con escala) mientras "Menor Distancia"/"Menor Tiempo" prefieran
        # este vuelo directo -- antes no existía este arco y por eso
        # cualquier consulta UIO->GPS quedaba forzada a pasar por GYE.
        ("UIO", "GPS", 1330, 130, 340, 270),
    ]
    for c1, c2, dist, tiem, cost, cons in datos_rutas:
        a1 = Aeropuerto.query.filter_by(codigo=c1).first()
        a2 = Aeropuerto.query.filter_by(codigo=c2).first()
        if not a1 or not a2:
            continue
        for origen_id, destino_id in [(a1.id, a2.id), (a2.id, a1.id)]:
            r = Ruta.query.filter_by(origen_id=origen_id, destino_id=destino_id).first()
            if r:
                r.distancia, r.tiempo, r.costo, r.consumo = dist, tiem, cost, cons
            else:
                db.session.add(Ruta(origen_id=origen_id, destino_id=destino_id, distancia=dist, tiempo=tiem, costo=cost, consumo=cons))
    db.session.commit()


# Se ejecuta siempre al importar el módulo (no solo con "python app.py"),
# para que también funcione bajo Gunicorn en Render -- antes, este bloque
# solo corría con "if __name__ == '__main__'", que Gunicorn nunca dispara,
# así que en producción la base de datos nunca se creaba.
with app.app_context():
    db.create_all()
    inicializar_bd()

if __name__ == "__main__":
    app.run(debug=True)