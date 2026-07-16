import json
import heapq
from flask import Flask, render_template, request, redirect, url_for
from config import Config
from models import db, Aeropuerto, Ruta, Simulacion

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

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
            # Penalización por evento dinámico: +50% al peso si hay Clima Adverso
            penalizacion = 1.5 if ruta.estado == "Clima Adverso" else 1.0
            
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
            # Detectar si pasamos por una zona con mal clima
            if ruta_padre.estado == "Clima Adverso":
                clima_adverso = True
        nodo_temp = padres[nodo_temp]
        
    # Asignar el mensaje final según las condiciones
    msj = "Ruta óptima calculada exitosamente. Condiciones climáticas normales."
    if clima_adverso:
        msj = "Precaución: La ruta calculada atraviesa zonas con Clima Adverso. Tiempos y costos penalizados."
        
    return camino_nodos, rutas_camino, msj

# --- RUTAS DE FLASK ---
@app.route("/")
def index():
    # Solo carga la pantalla de inicio con los perfiles
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
            except:
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
    
    # Variables de control para mantener seleccionadas las opciones
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
            # Calcular indicadores finales aplicando penalizaciones
            dist_total = 0
            tiempo_total = 0
            costo_total = 0
            consumo_total = 0

            for r in rutas_opt:
                distancia = r.distancia
                tiempo = r.tiempo
                costo = r.costo
                consumo = r.consumo

                if r.estado == "Clima Adverso":
                    distancia *= 1.05
                    tiempo *= 1.35
                    costo *= 1.20
                    consumo *= 1.25

                dist_total += distancia
                tiempo_total += tiempo
                costo_total += costo
                consumo_total += consumo

            dist_total = round(dist_total, 2)
            tiempo_total = round(tiempo_total, 2)
            costo_total = round(costo_total, 2)
            consumo_total = round(consumo_total, 2)
            
            origen_obj = Aeropuerto.query.get(origen_sel)
            destino_obj = Aeropuerto.query.get(destino_sel)
            nombres_ruta = " ➔ ".join([Aeropuerto.query.get(n).codigo for n in nodos])
            
            coordenadas = [{"lat": Aeropuerto.query.get(n).latitud, "lon": Aeropuerto.query.get(n).longitud, "info": Aeropuerto.query.get(n).codigo} for n in nodos]
            
            sim = Simulacion(origen=f"{origen_obj.ciudad} ({origen_obj.codigo})", destino=f"{destino_obj.ciudad} ({destino_obj.codigo})",
                             criterio=criterio_sel, distancia_total=dist_total, tiempo_total=tiempo_total,
                             costo_total=costo_total, consumo_total=consumo_total, nodos_ruta=nombres_ruta, estado_red=msj)
            db.session.add(sim)
            db.session.commit()
            
            simulaciones = Simulacion.query.order_by(Simulacion.id.desc()).limit(15).all()
            return render_template("rutas.html", aeropuertos=aeropuertos, simulaciones=simulaciones,
                                   mapa_ruta=json.dumps(coordenadas), error=msj if "Alerta" in msj else None, detalle=sim,
                                   origen_sel=origen_sel, destino_sel=destino_sel, criterio_sel=criterio_sel)
        else:
            return render_template("rutas.html", aeropuertos=aeropuertos, simulaciones=simulaciones, error=msj,
                                   origen_sel=origen_sel, destino_sel=destino_sel, criterio_sel=criterio_sel)
            
    return render_template("rutas.html", aeropuertos=aeropuertos, simulaciones=simulaciones, mapa_ruta="[]",
                           origen_sel=origen_sel, destino_sel=destino_sel, criterio_sel=criterio_sel)

def inicializar_bd():
    if Aeropuerto.query.count() == 0:
        db.session.add_all([
            Aeropuerto(codigo="UIO", nombre="MARISCAL SUCRE", ciudad="Quito", latitud=-0.1234, longitud=-78.3565),
            Aeropuerto(codigo="GYE", nombre="JOSÉ JOAQUÍN DE OLMEDO", ciudad="Guayaquil", latitud=-2.1574, longitud=-79.8835),
            Aeropuerto(codigo="CUE", nombre="MARISCAL LAMAR", ciudad="Cuenca", latitud=-2.9001, longitud=-79.0045),
            Aeropuerto(codigo="GPS", nombre="SEYMOUR BALTRA", ciudad="Galápagos", latitud=-0.4491, longitud=-90.2833),
            Aeropuerto(codigo="MEC", nombre="ELOY ALFARO", ciudad="Manta", latitud=-0.9474, longitud=-80.6781)
        ])
        db.session.commit()

    if Ruta.query.count() == 0:
        def crear_arista(c1, c2, dist, tiem, cost, cons):
            a1 = Aeropuerto.query.filter_by(codigo=c1).first()
            a2 = Aeropuerto.query.filter_by(codigo=c2).first()
            if a1 and a2:
                db.session.add(Ruta(origen_id=a1.id, destino_id=a2.id, distancia=dist, tiempo=tiem, costo=cost, consumo=cons))
                db.session.add(Ruta(origen_id=a2.id, destino_id=a1.id, distancia=dist, tiempo=tiem, costo=cost, consumo=cons))

        crear_arista("UIO", "GYE", 270, 45, 85.0, 130.0)
        crear_arista("UIO", "CUE", 310, 50, 95.0, 145.0)
        crear_arista("UIO", "MEC", 260, 40, 75.0, 120.0)
        crear_arista("GYE", "CUE", 130, 30, 50.0, 70.0)
        crear_arista("GYE", "GPS", 1170, 120, 200.0, 500.0)
        crear_arista("MEC", "GYE", 180, 35, 60.0, 90.0) 
        db.session.commit()

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        inicializar_bd()
    app.run(debug=True)