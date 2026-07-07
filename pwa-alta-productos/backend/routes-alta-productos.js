/**
 * Rutas Express para el Alta de Productos desde la PWA.
 *
 * PUNTOS DE INTEGRACIÓN (ajustar al backend real de la PWA):
 *   1. `odooExec`  -> reemplazar por el cliente Odoo que ya usa la PWA
 *      (el que sirve /api/products/:id/image). Firma esperada:
 *          async odooExec(model, method, args=[], kw={}) => result
 *   2. `requireRole` -> middleware de auth existente; limitar a los perfiles
 *      autorizados (Aaron / encargado de inventario).
 *   3. Montar el router en el server:  app.use('/api', require('./routes-alta-productos')(deps))
 */

const express = require("express");
const { crearProducto, withBackoff } = require("./crearProducto");

// Orden de tallas y grupos de corrida (criterio aprobado, validado contra Odoo)
const ORDEN_LETRAS = ["XS", "XS/S", "S", "S/M", "M", "M/L", "L", "L/XL", "XL", "XXL", "XXXL"];
function tallaKey(t) {
  const s = String(t).toUpperCase().trim();
  const x = s.match(/^([1-4])X$/);
  if (x) return [1, 100 + +x[1], ""];
  const i = ORDEN_LETRAS.indexOf(s);
  if (i >= 0) return [0, i, ""];
  const n = parseFloat(s === "CERO" ? "0" : s);
  if (!isNaN(n)) return [1, n, s];
  return [2, 0, s.toLowerCase()];
}
function tallaCmp(a, b) {
  const [ga, na, sa] = tallaKey(a), [gb, nb, sb] = tallaKey(b);
  return ga - gb || na - nb || sa.localeCompare(sb);
}
function grupoDe(t) {
  const s = String(t).trim();
  if (/unitalla|única/i.test(s)) return "Unitalla";
  if (/^[1-4]X$/i.test(s)) return "Extras";
  const n = parseFloat(/^cero$/i.test(s) ? "0" : s);
  if (isNaN(n)) return "Blusas (letras)";
  if (n >= 28) return "Pants 28-40";
  if (n % 2 === 1 && n <= 15) return "Dama 1-15";
  if (n >= 16 || n % 2 === 1) return "Extras";
  return "Pares 0-14";
}
const ORDEN_G = ["Dama 1-15", "Blusas (letras)", "Extras", "Pants 28-40", "Pares 0-14", "Unitalla"];

module.exports = function ({ odooExec, requireRole }) {
  const router = express.Router();
  const guard = requireRole ? requireRole(["admin", "inventario"]) : (_q, _s, next) => next();

  // --- Atributos en vivo: tallas (agrupadas) y colores (con frecuencia) ---
  router.get("/product-attributes", guard, async (req, res) => {
    try {
      const c = withBackoff(odooExec);
      const [tallas, colores] = await Promise.all([
        c("product.attribute.value", "search_read",
          [[["attribute_id", "=", 10]]], { fields: ["name"], order: "sequence,id" }),
        c("product.attribute.value", "search_read",
          [[["attribute_id", "=", 9]]], { fields: ["name", "html_color"], order: "sequence,id" }),
      ]);
      // agrupar tallas por corrida
      const grupos = {};
      [...new Set(tallas.map((t) => t.name.trim()))].forEach((t) => {
        (grupos[grupoDe(t)] = grupos[grupoDe(t)] || []).push(t);
      });
      ORDEN_G.forEach((g) => grupos[g] && grupos[g].sort(tallaCmp));
      res.json({
        tallas_grupos: ORDEN_G.filter((g) => grupos[g]).map((g) => ({ grupo: g, tallas: grupos[g] })),
        colores: colores.map((c) => ({ nombre: c.name, hex: c.html_color || null })),
      });
    } catch (e) {
      res.status(500).json({ error: e.message });
    }
  });

  // --- Alta de producto ---
  router.post("/products", guard, express.json({ limit: "25mb" }), async (req, res) => {
    const spec = req.body || {};
    // Validación de obligatorios
    const faltan = [];
    if (!spec.nombre) faltan.push("nombre");
    if (!spec.categoria) faltan.push("categoria");
    if (spec.costo == null) faltan.push("costo");
    for (const l of ["paquete", "corrida", "mayoreo", "menudeo"]) {
      if (!spec.precios || spec.precios[l] == null) faltan.push(`precio ${l}`);
    }
    if (faltan.length) return res.status(400).json({ error: "Faltan campos", faltan });

    try {
      const r = await crearProducto(odooExec, spec);
      res.json({ ok: true, ...r });
    } catch (e) {
      res.status(500).json({ ok: false, error: e.message });
    }
  });

  return router;
};
