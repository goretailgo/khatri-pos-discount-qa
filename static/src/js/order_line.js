/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";
import { Orderline } from "@point_of_sale/app/components/orderline/orderline";

function parseProductPriceJson(product) {
    try {
        let raw =
            (product && product.description) ||
            (product && product.description_picking) ||
            (product && product.description_sale) ||
            "";
        if (!raw || typeof raw !== "string") return null;
        // Strip HTML tags (e.g. <pre>, <p>) that Odoo's rich-text editor adds
        raw = raw.replace(/<[^>]*>/g, " ");
        // Decode common HTML entities
        raw = raw.replace(/&nbsp;/g, " ")
                 .replace(/&amp;/g, "&")
                 .replace(/&quot;/g, '"')
                 .replace(/&#34;/g, '"')
                 .replace(/&lt;/g, "<")
                 .replace(/&gt;/g, ">");
        // Extract the JSON block
        const match = raw.match(/\{[\s\S]*\}/);
        if (!match) return null;
        return JSON.parse(match[0]);
    } catch (e) {
        console.warn("Khatri JSON parse failed:", e);
        return null;
    }
}

function resolveLineDiscount(product, steppedEffective) {
    const cfg = parseProductPriceJson(product);
    if (!cfg) {
        return { discount: steppedEffective, useCustom: false, type: "stepped", customDiscount: 0 };
    }
    if (cfg.price_list_default === true) {
        return { discount: steppedEffective, useCustom: false, type: "stepped", customDiscount: 0 };
    }
    if (cfg.percentage_profit && typeof cfg.percentage_profit === "object") {
        const discountPct = parseFloat(cfg.percentage_profit.discount) || 0;
        return { discount: discountPct, useCustom: true, type: "percentage_profit", customDiscount: discountPct };
    }
    if (cfg.flat && typeof cfg.flat === "object") {
        const discountPct = parseFloat(cfg.flat.discount) || 0;
        return { discount: discountPct, useCustom: true, type: "flat", customDiscount: discountPct };
    }
    return { discount: 0, useCustom: true, type: "none", customDiscount: 0 };
}

function getSteppedEffective(config) {
    if (!config) return 0;
    const d1 = parseFloat(config.khatri_first_discount) || 0;
    const useSecond = config.khatri_enable_second_discount;
    const d2 = useSecond ? (parseFloat(config.khatri_second_discount) || 0) : 0;
    if (useSecond && d2 > 0) {
        return 100 * (1 - (1 - d1 / 100) * (1 - d2 / 100));
    }
    return d1;
}

patch(PosStore.prototype, {
    async addLineToCurrentOrder(vals, opts = {}, configure = true) {
        // Merge quantity for existing lines (preserve original behaviour)
        try {
            const config = this.config;
            if (config && config.khatri_enable_stepped_discount) {
                const order = this.getOrder();
                if (order && vals.product_id) {
                    const productId = vals.product_id.id || vals.product_id;
                    const existingLine = order.lines.find(line =>
                        ((line.product_id && line.product_id.id) || line.product_id) === productId &&
                        !line.refunded_orderline_id
                    );
                    if (existingLine) {
                        const addQty = vals.qty || opts.quantity || 1;
                        existingLine.setQuantity(existingLine.getQuantity() + addQty);
                        this.selectOrderLine(order, existingLine);
                        return existingLine;
                    }
                }
            }
        } catch (e) {
            console.error("Khatri merge error:", e);
        }

        // Create the line normally
        const line = await super.addLineToCurrentOrder(vals, opts, configure);

        // Now apply the correct discount, reading product JSON from the created line
        try {
            const config = this.config;
            if (line && config && config.khatri_enable_stepped_discount) {
                const steppedEffective = getSteppedEffective(config);
                const product = line.product_id;
                const resolved = resolveLineDiscount(product, steppedEffective);
                line.discount = resolved.discount;
            }
        } catch (e) {
            console.error("Khatri discount error:", e);
        }

        return line;
    },
});

// Helpers exposed to BOTH Orderline and OrderReceipt components
const khatriHelpers = {
    khatriLineIndex(line) {
        try {
            if (!line || !line.order_id || !line.order_id.lines) return 1;
            return line.order_id.lines.indexOf(line) + 1;
        } catch (e) { return 1; }
    },
    khatriLineDiscountPct(line) {
        try {
            if (!line || !line.order_id || !line.order_id.config) return 0;
            const config = line.order_id.config;
            if (!config.khatri_enable_stepped_discount) return 0;
            const steppedEffective = getSteppedEffective(config);
            const resolved = resolveLineDiscount(line.product_id, steppedEffective);
            if (resolved.type !== "stepped" && resolved.discount > 0) {
                return resolved.discount;
            }
            return 0;
        } catch (e) { return 0; }
    },
    khatriNotStepped(line) {
        return !this.khatriIsStepped(line);
    },
    khatriIsStepped(line) {
        try {
            return !!(line && line.order_id && line.order_id.config &&
                      line.order_id.config.khatri_enable_stepped_discount);
        } catch (e) { return false; }
    },
    khatriCategoryName(line) {
        try {
            if (line && line.product_id && line.product_id.pos_categ_ids &&
                line.product_id.pos_categ_ids.length > 0) {
                return line.product_id.pos_categ_ids[0].name;
            }
        } catch (e) {}
        return "";
    },
    khatriLineMrp(line) {
        try {
            const sym = (line && line.currency && line.currency.symbol) || "";
            const total = (line.price_unit || 0) * (line.qty || 1);
            return sym + total.toFixed(2);
        } catch (e) { return ""; }
    },
    khatriLineInfo(line) {
        try {
            if (!line || !line.order_id || !line.order_id.config) return null;
            const config = line.order_id.config;
            if (!config.khatri_enable_stepped_discount) return null;
            const steppedEffective = getSteppedEffective(config);
            const resolved = resolveLineDiscount(line.product_id, steppedEffective);
            return {
                type: resolved.type,
                discountPct: resolved.discount,
            };
        } catch (e) { return null; }
    },
};

patch(Orderline.prototype, khatriHelpers);
patch(OrderReceipt.prototype, khatriHelpers);

patch(OrderReceipt.prototype, {
    khatriNoStep(info) {
        return info ? !info.hasAnyStepped : false;
    },
    getKhatriOrderInfo() {
        try {
            const order = this.props.order;
            if (!order) return null;
            const config = order.config;
            if (!config || !config.khatri_enable_stepped_discount) return null;

            const d1 = parseFloat(config.khatri_first_discount) || 0;
            const useSecond = config.khatri_enable_second_discount;
            const d2 = useSecond ? (parseFloat(config.khatri_second_discount) || 0) : 0;
            const steppedEffective = getSteppedEffective(config);

            let totalOriginal = 0, totalFinal = 0;
            let steppedOriginal = 0, steppedFinal = 0;
            let customOriginal = 0, customFinal = 0;
            let hasAnyStepped = false, hasAnyCustom = false;
            let customPct = 0;

            for (const line of order.lines || []) {
                const orig = (line.price_unit || 0) * (line.qty || 1);
                totalOriginal += orig;
                const resolved = resolveLineDiscount(line.product_id, steppedEffective);
                const fin = orig * (1 - resolved.discount / 100);
                totalFinal += fin;

                if (resolved.type === "stepped") {
                    hasAnyStepped = true;
                    steppedOriginal += orig;
                    steppedFinal += fin;
                } else {
                    hasAnyCustom = true;
                    customOriginal += orig;
                    customFinal += fin;
                    if (resolved.discount > 0) customPct = resolved.discount;
                }
            }

            return {
                d1, d2, useSecond, steppedEffective,
                totalOriginal, totalFinal,
                totalSaved: totalOriginal - totalFinal,
                steppedOriginal, steppedFinal,
                steppedSaved: steppedOriginal - steppedFinal,
                customOriginal, customFinal,
                customSaved: customOriginal - customFinal,
                hasAnyStepped, hasAnyCustom,
                customDiscountPct: customPct,
                isMixed: hasAnyStepped && hasAnyCustom,
            };
        } catch (e) {
            console.error("Khatri discount error:", e);
            return null;
        }
    },

    // Return lines that use the stepped 50+25 discount
    khatriSteppedLines() {
        try {
            const order = this.props.order;
            if (!order || !order.config) return [];
            const eff = getSteppedEffective(order.config);
            return (order.lines || []).filter(l => {
                const r = resolveLineDiscount(l.product_id, eff);
                return r.type === "stepped";
            });
        } catch (e) { return []; }
    },

    // Return lines that use a custom (flat / percentage_profit) discount
    khatriCustomLines() {
        try {
            const order = this.props.order;
            if (!order || !order.config) return [];
            const eff = getSteppedEffective(order.config);
            return (order.lines || []).filter(l => {
                const r = resolveLineDiscount(l.product_id, eff);
                return r.type !== "stepped";
            });
        } catch (e) { return []; }
    },

    // Currency-formatted MRP (original) for a single line, no symbol logic duplicated
    khatriLineMrpNum(line) {
        try { return (line.price_unit || 0) * (line.qty || 1); } catch (e) { return 0; }
    },

    // Final (discounted) price for a single line
    khatriLineFinalNum(line) {
        try {
            const order = this.props.order;
            const eff = getSteppedEffective(order.config);
            const r = resolveLineDiscount(line.product_id, eff);
            const mrp = (line.price_unit || 0) * (line.qty || 1);
            return mrp * (1 - r.discount / 100);
        } catch (e) { return 0; }
    },

    // Discount % for a single line (for display)
    khatriLinePct(line) {
        try {
            const order = this.props.order;
            const eff = getSteppedEffective(order.config);
            const r = resolveLineDiscount(line.product_id, eff);
            return r.discount;
        } catch (e) { return 0; }
    },

    // Product display name for a line
    khatriLineName(line) {
        try {
            return (line.product_id && line.product_id.display_name) || "";
        } catch (e) { return ""; }
    },
});
