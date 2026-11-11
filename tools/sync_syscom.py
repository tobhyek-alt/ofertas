#!/usr/bin/env python3
"""Descarga el catálogo con existencia desde la API oficial de distribuidores
y genera los archivos públicos del catálogo (sin costos).

Variables de entorno (secretos de GitHub):
  SYSCOM_TOKEN                     token de acceso (válido 1 año), o bien
  SYSCOM_CLIENT_ID + SYSCOM_CLIENT_SECRET   para generar el token
  MARGEN                           opcional, por defecto 0.15

Salida: catalogo/index.json y catalogo/c<ID>.json (uno por categoría).
Nunca escribe el costo: solo el precio de venta ya con margen.
"""
import json, math, os, sys, time, urllib.parse, urllib.request, urllib.error, datetime

BASE = os.environ.get("SYSCOM_BASE") or "https://developers.syscom.mx/api/v1"
OUT = sys.argv[1] if len(sys.argv) > 1 else "catalogo"
MARGEN = float(os.environ.get("MARGEN") or 0.15)
PAUSA = 1.1  # la API limita peticiones por minuto


def log(*a):
    print(*a, flush=True)


def http(method, url, data=None, token=None, intentos=6):
    headers = {"Accept": "application/json", "User-Agent": "catalogo-ofertas/1.0"}
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if token:
        headers["Authorization"] = "Bearer " + token
    for n in range(intentos):
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                time.sleep(PAUSA)
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                espera = int(e.headers.get("Retry-After") or 0) or (5 * (n + 1))
                log(f"  {e.code}, reintento en {espera}s")
                time.sleep(espera)
                continue
            msg = e.read().decode("utf-8", "replace")[:300]
            raise SystemExit(f"Error {e.code} en {url.split('?')[0]}: {msg}")
        except urllib.error.URLError as e:
            log(f"  red: {e}; reintento")
            time.sleep(5 * (n + 1))
    raise SystemExit(f"Sin respuesta de {url.split('?')[0]}")


def token():
    t = (os.environ.get("SYSCOM_TOKEN") or "").strip()
    if t:
        return t
    cid = (os.environ.get("SYSCOM_CLIENT_ID") or "").strip()
    sec = (os.environ.get("SYSCOM_CLIENT_SECRET") or "").strip()
    if not (cid and sec):
        raise SystemExit("Faltan los secretos SYSCOM_TOKEN o SYSCOM_CLIENT_ID/SYSCOM_CLIENT_SECRET")
    r = http("POST", BASE + "/oauth/token",
             {"grant_type": "client_credentials", "client_id": cid, "client_secret": sec})
    return r["access_token"]


def num(v):
    try:
        x = float(str(v).replace(",", ""))
        return x if x > 0 else None
    except (TypeError, ValueError):
        return None


def end9(x):
    n = math.ceil(x)
    return n + ((9 - n % 10) % 10)


def lista(r):
    if isinstance(r, list):
        return r, 1
    prods = r.get("productos") or r.get("data") or []
    paginas = int(r.get("paginas") or r.get("total_paginas") or 1)
    return prods, paginas


def precio_venta(p):
    pr = p.get("precios") or {}
    if not isinstance(pr, dict):
        return None
    costo = num(pr.get("precio_descuento")) or num(pr.get("precio_especial")) or num(pr.get("precio_1"))
    if not costo:
        return None
    venta = end9(costo * (1 + MARGEN))
    minimo = num(pr.get("precio_map"))
    if minimo and venta < minimo:
        venta = end9(minimo)
    return venta


def existencia(p):
    v = p.get("total_existencia")
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def subcat(p, nivel1):
    for c in p.get("categorias") or []:
        if str(c.get("nivel")) == "2":
            return c.get("nombre")
    return nivel1


def main():
    tk = token()
    cats = http("GET", BASE + "/categorias", token=tk)
    cats = [c for c in cats if str(c.get("nivel", "1")) == "1"]
    log(f"{len(cats)} categorías")
    os.makedirs(OUT, exist_ok=True)
    vistos, indice, total = set(), [], 0
    for c in cats:
        cid, nombre = str(c["id"]), c.get("nombre", "").strip()
        items, pag, paginas = [], 1, 1
        while pag <= paginas and pag <= 1000:
            q = urllib.parse.urlencode({"categoria": cid, "stock": 1, "moneda": "mxn", "iva": 1,
                                        "limit": 1000, "pagina": pag})
            prods, paginas = lista(http("GET", f"{BASE}/productos?{q}", token=tk))
            if not prods:
                break
            for p in prods:
                pid = str(p.get("producto_id") or p.get("id") or "")
                if not pid or pid in vistos:
                    continue
                if p.get("venta_permitida_en_ecommerce") in (False, 0, "0", "false"):
                    continue
                st = existencia(p)
                venta = precio_venta(p)
                if st <= 0 or not venta:
                    continue
                vistos.add(pid)
                items.append({
                    "id": pid,
                    "t": (p.get("titulo") or "").strip(),
                    "m": (p.get("marca") or "").strip(),
                    "mo": (p.get("modelo") or "").strip(),
                    "s": subcat(p, nombre),
                    "img": p.get("img_portada") or "",
                    "p": venta,
                    "e": min(st, 999),
                })
            pag += 1
        if items:
            items.sort(key=lambda x: (x["s"] or "", x["p"]))
            with open(os.path.join(OUT, f"c{cid}.json"), "w", encoding="utf-8") as f:
                json.dump(items, f, ensure_ascii=False, separators=(",", ":"))
            indice.append({"id": cid, "n": nombre, "k": len(items)})
            total += len(items)
        log(f"  {nombre}: {len(items)}")
    if not total:
        raise SystemExit("La API no devolvió productos con existencia; no se publica nada.")
    ahora = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-6)))
    with open(os.path.join(OUT, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"actualizado": ahora.strftime("%Y-%m-%d %H:%M"), "total": total, "categorias": indice},
                  f, ensure_ascii=False, separators=(",", ":"))
    log(f"Total publicado: {total}")


if __name__ == "__main__":
    main()
