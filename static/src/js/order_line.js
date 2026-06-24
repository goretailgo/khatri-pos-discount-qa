/** @odoo-module **/
import { onMounted } from "@odoo/owl";

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
    if (!config.khatri_enable_stepped_discount) return 0;
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
            // Always merge the same product (matched by product ID) into one line,
            // regardless of the stepped-discount toggle. Different products that share
            // a name but have different IDs/barcodes stay as separate lines.
            if (config) {
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
            if (line && config) {
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
    setup() {
        super.setup(...arguments);
        onMounted(() => {
            try {
                document.querySelectorAll('.pos-receipt-order-data').forEach(function(el) {
                    if (el.textContent && el.textContent.indexOf('Powered by') !== -1) {
                        el.style.display = 'none';
                    }
                });
            } catch (e) {}
        });
    },
    khatriNoStep(info) {
        return info ? !info.hasAnyStepped : false;
    },
    getKhatriOrderInfo() {
        try {
            const order = this.props.order;
            if (!order) return null;
            const config = order.config;
            if (!config) return null;

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
                const lineDisc = parseFloat(line.discount) || 0;
                const fin = orig * (1 - lineDisc / 100);
                totalFinal += fin;

                if (resolved.type === "stepped") {
                    hasAnyStepped = true;
                    steppedOriginal += orig;
                    steppedFinal += fin;
                } else {
                    hasAnyCustom = true;
                    customOriginal += orig;
                    customFinal += fin;
                    if ((parseFloat(line.discount) || 0) > 0) customPct = parseFloat(line.discount) || 0;
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
            const lineDisc = parseFloat(line.discount) || 0;
            const mrp = (line.price_unit || 0) * (line.qty || 1);
            return mrp * (1 - lineDisc / 100);
        } catch (e) { return 0; }
    },

    // Discount % for a single line (for display)
    khatriLinePct(line) {
        try {
            return parseFloat(line.discount) || 0;
        } catch (e) { return 0; }
    },

    // Product display name for a line
    // Unit MRP (per single unit, not multiplied by qty)
    khatriLineUnitMrp(line) {
        try { return line.price_unit || 0; } catch (e) { return 0; }
    },

    // Unit final price (per single unit, after discount)
    khatriLineUnitFinal(line) {
        try {
            const lineDisc = parseFloat(line.discount) || 0;
            return (line.price_unit || 0) * (1 - lineDisc / 100);
        } catch (e) { return 0; }
    },

    // Whether this line actually has a discount applied (> 0)
    khatriLineNoDiscount(line) {
        return !this.khatriLineHasDiscount(line);
    },
    khatriLineHasDiscount(line) {
        try {
            return (parseFloat(line.discount) || 0) > 0;
        } catch (e) { return false; }
    },

    khatriGetConfig() {
        try {
            const order = this.props.order;
            if (order && order.config) return order.config;
        } catch (e) {}
        try {
            if (this.pos && this.pos.config) return this.pos.config;
        } catch (e) {}
        try {
            if (this.env && this.env.services && this.env.services.pos && this.env.services.pos.config) return this.env.services.pos.config;
        } catch (e) {}
        return null;
    },
    khatriSectionAHeading() {
        try {
            const info = this.getKhatriOrderInfo();
            if (!info || !(info.steppedSaved > 0)) {
                return "SECTION A";
            }
            if (info.useSecond && info.d2 > 0) {
                return "SECTION A : " + info.d1 + "% + " + info.d2 + "% Discount";
            }
            return "SECTION A : " + info.d1 + "% Discount";
        } catch (e) {
            return "SECTION A";
        }
    },
    khatriReceiptContact() {
        return "+919981161544";
    },
    khatriReceiptLogo() {
        return "data:image/png;base64,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";
    },
    khatriLineName(line) {
        try {
            return (line.product_id && line.product_id.display_name) || "";
        } catch (e) { return ""; }
    },
});
