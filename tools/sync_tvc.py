#!/usr/bin/env python3
"""Descarga el catálogo con existencia desde la API TVC Connect (api.tvc.mx)
y genera los archivos públicos del catálogo, sin costos.

Variables de entorno (secretos/variables de GitHub):
  TVC_TOKEN   token Bearer de TVC Connect (vigencia 1 año)
  MARGEN      opcional, por defecto 0.15 (15 % sobre tu costo)

Salida: <carpeta>/index.json y <carpeta>/c<N>.json (uno por categoría principal).
Solo se publica el precio de venta ya con margen e IVA.
"""
import json, math, os, re, sys, time, urllib.parse, urllib.request, urllib.error, datetime

BASE = os.environ.get("TVC_BASE") or "https://api.tvc.mx"
OUT = sys.argv[1] if len(sys.argv) > 1 else "catalogo"
MARGEN = float(os.environ.get("MARGEN") or 0.15)
IVA = 1.16
PAUSA = 0.7          # ~85 peticiones por minuto, muy debajo del límite de 200
POR_PAGINA = 100     # máximo que permite la API
CDN = "https://cdn.tvc.mx"


def log(*a):
    print(*a, flush=True)


def limpiar(v):
    v = (v or "").strip().strip('"').strip("'").strip()
    if v.lower().startswith("bearer "):
        v = v[7:].strip()
    return v


TOKEN = None


def candidatos():
    tok, tid = limpiar(os.environ.get("TVC_TOKEN")), limpiar(os.environ.get("TVC_TOKEN_ID"))
    if not tok:
        raise SystemExit("Falta el secreto TVC_TOKEN")
    c = [tok]
    if tid and "|" not in tok:
        c.append(f"{tid}|{tok}")      # formato id|token
        c.append(f"{tok}|{tid}")      # por si se capturaron al revés
    return c


def autenticar():
    global TOKEN
    for i, t in enumerate(candidatos()):
        req = urllib.request.Request(BASE + "/exchange-rates", headers={
            "Authorization": "Bearer " + t, "Accept": "application/json", "User-Agent": "catalogo-ofertas/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=60):
                TOKEN = t
                print(f"::notice::Token aceptado (formato {i + 1})", flush=True)
                return
        except urllib.error.HTTPError as e:
            if e.code != 401:
                raise SystemExit(f"Error {e.code} al validar el token")
        time.sleep(PAUSA)
    raise SystemExit("TVC rechazó el token (401 Unauthenticated). Revisa que el secreto TVC_TOKEN tenga el token completo"
                     " y, si TVC te dio un ID aparte, guárdalo en el secreto TVC_TOKEN_ID.")


def get(path, params=None, intentos=6):
    tok = TOKEN
    url = BASE + path + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
    hdr = {"Authorization": "Bearer " + tok, "Accept": "application/json",
           "User-Agent": "catalogo-ofertas/1.0"}
    for n in range(intentos):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=120) as r:
                time.sleep(PAUSA)
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                espera = int(e.headers.get("Retry-After") or 0) or 10 * (n + 1)
                log(f"  {e.code}; reintento en {espera}s")
                time.sleep(espera)
                continue
            cuerpo = e.read().decode("utf-8", "replace")[:300]
            raise SystemExit(f"Error {e.code} en {path}: {cuerpo}")
        except urllib.error.URLError as e:
            log(f"  red: {e}; reintento")
            time.sleep(10 * (n + 1))
    raise SystemExit(f"Sin respuesta de {path}")


def num(v):
    try:
        x = float(str(v).replace(",", "").replace("$", "").strip())
        return x if x > 0 else None
    except (TypeError, ValueError):
        return None


def end9(x):
    n = math.ceil(x)
    return n + ((9 - n % 10) % 10)


def tipo_cambio():
    r = get("/exchange-rates")
    if isinstance(r, dict):
        for k in ("data", "exchange_rate", "rate", "tipo_cambio", "value"):
            if k in r:
                r = r[k]
                break
    if isinstance(r, list) and r:
        r = r[0]
    if isinstance(r, dict):
        r = next((v for v in r.values() if num(v)), None)
    print(f"::notice::exchange-rates -> {str(r)[:120]}", flush=True)
    tc = num(r)
    if not tc or not (10 < tc < 40):
        raise SystemExit(f"Tipo de cambio inesperado: {r!r}")
    return tc


def existencia(p):
    v = p.get("total_inventories")
    if v is None and isinstance(p.get("inventories"), dict):
        v = p["inventories"].get("total")
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def costo_mxn(p, tc):
    c = num(p.get("distributor_price"))
    if not c:
        return None
    moneda = str(p.get("currency") or p.get("currency_code") or "USD").upper()
    return c * (tc if moneda.startswith("USD") or moneda == "DLS" else 1)


def raiz(p):
    t = p.get("category_breadcrumb_tree")
    while isinstance(t, dict) and isinstance(t.get("parent"), dict):
        t = t["parent"]
    if isinstance(t, dict) and t.get("name"):
        nombre = t["name"].strip()
    else:
        bc = p.get("category_breadcrumb") or p.get("category") or "Otros"
        nombre = re.split(r"\s*[>/]\s*", bc)[0].strip() or "Otros"
    return re.sub(r"[^a-z0-9]+", "", nombre.lower())[:24] or "otros", nombre


def sub(p):
    bc = p.get("category_breadcrumb") or ""
    partes = [x for x in re.split(r"\s*[>/]\s*", bc) if x]
    return partes[1] if len(partes) > 1 else (p.get("category") or "")


def imagen(p):
    m = p.get("media") or {}
    u = m.get("main_image") if isinstance(m, dict) else None
    if not u:
        return ""
    u = u.replace("\\/", "/")
    return u if u.startswith("http") else CDN + ("" if u.startswith("/") else "/") + u


def nombre(p):
    n = re.sub(r"\s+", " ", (p.get("name") or "")).strip()
    return re.sub(r"\s#\S+", "", n)  # quita etiquetas internas tipo #CAM


def main():
    autenticar()
    tc = tipo_cambio()
    log(f"Tipo de cambio: {tc}")
    cats, vistos, pagina, ultima = {}, set(), 1, None
    params = {"withInventory": "simple", "withPrice": "true", "withMedia": "true",
              "withCategoryBreadcrumb": "true", "perPage": POR_PAGINA}
    while True:
        r = get("/products", dict(params, page=pagina))
        if pagina == 1:
            muestra = (r.get("data") or [{}])[0] if isinstance(r, dict) else (r or [{}])[0]
            print("::notice::products keys=" + ",".join(sorted(r.keys()) if isinstance(r, dict) else ["lista"])
                  + " | producto=" + ",".join(sorted(muestra.keys()))[:600]
                  + f" | precio={muestra.get('distributor_price')!r} lista={muestra.get('list_price')!r} moneda={muestra.get('currency')!r} inv={muestra.get('total_inventories')!r}", flush=True)
        datos = r.get("data") if isinstance(r, dict) else r
        if not datos:
            break
        if ultima is None and isinstance(r, dict):
            meta = r.get("meta") if isinstance(r.get("meta"), dict) else r
            ultima = int(meta.get("last_page") or 0) or None
            if ultima:
                log(f"{ultima} páginas")
        for p in datos:
            pid = str(p.get("tvc_id") or p.get("id") or "")
            if not pid or pid in vistos:
                continue
            if str(p.get("stage_name") or "Activo").lower() not in ("activo", "active"):
                continue
            st = existencia(p)
            costo = costo_mxn(p, tc)
            if st <= 0 or not costo:
                continue
            vistos.add(pid)
            cid, cnom = raiz(p)
            cats.setdefault(cid, {"n": cnom, "items": []})["items"].append({
                "id": pid,
                "t": nombre(p),
                "m": (p.get("brand") or "").strip(),
                "mo": (p.get("provider_model") or p.get("tvc_model") or "").strip(),
                "s": sub(p),
                "img": imagen(p),
                "p": end9(costo * IVA * (1 + MARGEN)),
                "e": min(st, 999),
            })
        if pagina % 20 == 0:
            log(f"  página {pagina}: {len(vistos)} productos con existencia")
        links = r.get("links") if isinstance(r, dict) else None
        if (ultima and pagina >= ultima) or (isinstance(links, dict) and "next" in links and not links["next"]):
            break
        if len(datos) < POR_PAGINA:
            break
        pagina += 1
        if pagina > 2000:
            break
    os.makedirs(OUT, exist_ok=True)
    indice, total = [], 0
    for n, (cid, c) in enumerate(sorted(cats.items(), key=lambda kv: -len(kv[1]["items"]))):
        items = sorted(c["items"], key=lambda x: (x["s"], x["p"]))
        clave = re.sub(r"\W+", "", cid) or str(n)
        with open(os.path.join(OUT, f"c{clave}.json"), "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, separators=(",", ":"))
        indice.append({"id": clave, "n": c["n"], "k": len(items)})
        total += len(items)
        log(f"  {c['n']}: {len(items)}")
    if not total:
        raise SystemExit("La API no devolvió productos con existencia; no se publica nada.")
    ahora = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-6)))
    with open(os.path.join(OUT, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"actualizado": ahora.strftime("%Y-%m-%d %H:%M"), "total": total, "categorias": indice},
                  f, ensure_ascii=False, separators=(",", ":"))
    log(f"Total publicado: {total} productos en {len(indice)} categorías")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        if e.code not in (None, 0):
            # aparece como anotación visible en GitHub (sin datos sensibles)
            print(f"::error::{e.code}", flush=True)
        raise
    except Exception as e:
        print(f"::error::{type(e).__name__}: {str(e)[:300]}", flush=True)
        raise
