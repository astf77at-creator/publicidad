/**
 * Motor de alta de productos para YOOHOO (Node.js) — port del motor Python
 * validado end-to-end contra yoohoo2.odoo.com.
 *
 * Diseñado para plugin: recibe una función `exec(model, method, args, kw)` que
 * ejecuta un execute_kw contra Odoo. Así se integra con el cliente Odoo que ya
 * usa el backend Express de la PWA (o con el helper `odooExecute` de abajo).
 *
 * IDs reales verificados en yoohoo2 (SaaS 19.2):
 *   Atributos: Tallas=10, Colour=9
 *   Listas de precio: Paquetes=13, Corridas=3, Mayoreo=4, Menudeo=15(=list_price)
 *   Marca: campo Studio x_studio_marca_id -> modelo x_marca (campo x_name)
 *   Productos SIN impuesto (taxes_id vacío)
 */

const ATTR_TALLA = 10;
const ATTR_COLOR = 9;
const PRICELIST = { paquete: 13, corrida: 3, mayoreo: 4, menudeo: 15 };
const MARCA_MODEL = "x_marca";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * Envuelve una llamada exec con reintento/backoff ante el 429 de Odoo SaaS.
 * @param {Function} exec  async (model, method, args=[], kw={}) => result
 */
function withBackoff(exec) {
  return async function (model, method, args = [], kw = {}) {
    let delay = 2000;
    for (let intento = 0; intento < 5; intento++) {
      try {
        return await exec(model, method, args, kw);
      } catch (e) {
        const is429 =
          e.statusCode === 429 ||
          e.code === 429 ||
          /429|Too Many Requests/i.test(e.message || "");
        if (is429 && intento < 4) {
          await sleep(delay);
          delay *= 2;
          continue;
        }
        throw e;
      }
    }
  };
}

async function resolverCategoria(c, nombre) {
  let cat = await c("product.category", "search", [[["name", "=", nombre]]], { limit: 1 });
  const categId = cat.length ? cat[0] : await c("product.category", "create", [{ name: nombre }]);
  let pos = await c("pos.category", "search", [[["name", "=", nombre]]], { limit: 1 });
  let pub = await c("product.public.category", "search", [[["name", "=", nombre]]], { limit: 1 });
  const posIds = pos.length ? pos : [await c("pos.category", "create", [{ name: nombre }])];
  const pubIds = pub.length ? pub : [await c("product.public.category", "create", [{ name: nombre }])];
  return { categId, posIds, pubIds };
}

async function resolverMarca(c, nombre) {
  if (!nombre) return false;
  const m = await c(MARCA_MODEL, "search", [[["x_name", "=", nombre]]], { limit: 1 });
  return m.length ? m[0] : await c(MARCA_MODEL, "create", [{ x_name: nombre }]);
}

async function valoresAttr(c, attrId, nombres) {
  const ids = [];
  for (const n of nombres) {
    const v = await c("product.attribute.value", "search",
      [[["attribute_id", "=", attrId], ["name", "=", n]]], { limit: 1 });
    ids.push(v.length ? v[0]
      : await c("product.attribute.value", "create", [{ attribute_id: attrId, name: n }]));
  }
  return ids;
}

/**
 * Crea un producto completo en Odoo.
 * @param {Function} exec  cliente execute_kw: (model, method, args, kw) => result
 * @param {Object} spec    ver README (nombre, categoria, sku, marca, costo,
 *                          precios{paquete,corrida,mayoreo,menudeo}, pos,
 *                          tallas[], colores[], foto_delantera, galeria[],
 *                          cantidad_inicial, location_id)
 * @returns {Promise<{template_id, variant_ids, categ_id, pos_ids, public_ids, marca_id}>}
 */
async function crearProducto(exec, spec) {
  const c = withBackoff(exec);

  const { categId, posIds, pubIds } = await resolverCategoria(c, spec.categoria);
  const marcaId = await resolverMarca(c, spec.marca);

  const attrLines = [];
  if (spec.tallas && spec.tallas.length) {
    attrLines.push([0, 0, {
      attribute_id: ATTR_TALLA,
      value_ids: [[6, 0, await valoresAttr(c, ATTR_TALLA, spec.tallas)]],
    }]);
  }
  if (spec.colores && spec.colores.length) {
    attrLines.push([0, 0, {
      attribute_id: ATTR_COLOR,
      value_ids: [[6, 0, await valoresAttr(c, ATTR_COLOR, spec.colores)]],
    }]);
  }

  const vals = {
    name: spec.nombre,
    categ_id: categId,
    pos_categ_ids: [[6, 0, posIds]],
    public_categ_ids: [[6, 0, pubIds]],
    default_code: spec.sku || false,
    list_price: spec.precios.menudeo,   // menudeo = precio base
    taxes_id: [[6, 0, []]],             // productos yoohoo2 sin impuesto
    type: "consu",
    is_storable: true,
    available_in_pos: spec.pos !== false,
    attribute_line_ids: attrLines,
  };
  if (marcaId) vals.x_studio_marca_id = marcaId;
  if (spec.foto_delantera) vals.image_1920 = spec.foto_delantera;

  const tmplId = await c("product.template", "create", [vals]);

  // Reglas de precio en las 3 listas restantes
  for (const lista of ["paquete", "corrida", "mayoreo"]) {
    const precio = spec.precios[lista];
    if (precio) {
      await c("product.pricelist.item", "create", [{
        pricelist_id: PRICELIST[lista],
        applied_on: "1_product",
        product_tmpl_id: tmplId,
        compute_price: "fixed",
        fixed_price: precio,
        min_quantity: 0,
      }]);
    }
  }

  // Galería (trasera + proveedor)
  for (const img of spec.galeria || []) {
    await c("product.image", "create", [{
      product_tmpl_id: tmplId, name: img.name, image_1920: img.data,
    }]);
  }

  const variantIds = await c("product.product", "search", [[["product_tmpl_id", "=", tmplId]]]);

  // Costo: standard_price se almacena por variante en Odoo 19
  if (spec.costo) {
    await c("product.product", "write", [variantIds, { standard_price: spec.costo }]);
  }

  // Inventario inicial (opcional)
  if (spec.cantidad_inicial && spec.location_id) {
    const quantIds = [];
    for (const vid of variantIds) {
      quantIds.push(await c("stock.quant", "create", [{
        product_id: vid, location_id: spec.location_id,
        inventory_quantity: spec.cantidad_inicial,
      }]));
    }
    // action_apply_inventory devuelve None (XML-RPC no serializa None) — se tolera,
    // el conteo ya se aplicó como efecto en el servidor.
    try {
      await c("stock.quant", "action_apply_inventory", [quantIds]);
    } catch (e) {
      if (!/marshal None|cannot marshal/i.test(e.message || "")) throw e;
    }
  }

  return {
    template_id: tmplId, variant_ids: variantIds,
    categ_id: categId, pos_ids: posIds, public_ids: pubIds, marca_id: marcaId,
  };
}

module.exports = { crearProducto, withBackoff, PRICELIST, ATTR_TALLA, ATTR_COLOR };
