/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";

patch(PosStore.prototype, {
    async addLineToCurrentOrder(vals, opts = {}, configure = true) {
        try {
            const config = this.config;
            if (config && config.khatri_enable_stepped_discount) {
                const d1 = parseFloat(config.khatri_first_discount) || 0;
                const useSecond = config.khatri_enable_second_discount;
                const d2 = useSecond ? (parseFloat(config.khatri_second_discount) || 0) : 0;

                let effective;
                if (useSecond && d2 > 0) {
                    effective = 100 * (1 - (1 - d1 / 100) * (1 - d2 / 100));
                } else {
                    effective = d1;
                }

                const order = this.getOrder();
                if (order && vals.product_id) {
                    const productId = vals.product_id.id || vals.product_id;
                    const existingLine = order.lines.find(line =>
                        (line.product_id?.id || line.product_id) === productId &&
                        !line.refunded_orderline_id
                    );
                    if (existingLine) {
                        const addQty = vals.qty || opts.quantity || 1;
                        existingLine.setQuantity(existingLine.getQuantity() + addQty);
                        this.selectOrderLine(order, existingLine);
                        return existingLine;
                    }
                }
                vals = { ...vals, discount: effective };
            }
        } catch(e) {
            console.error("Khatri error:", e);
        }
        return await super.addLineToCurrentOrder(vals, opts, configure);
    },
});

patch(OrderReceipt.prototype, {
    getKhatriOrderInfo() {
        try {
            const order = this.props.order;
            if (!order) return null;
            const config = order.config;
            if (!config || !config.khatri_enable_stepped_discount) return null;

            const d1 = parseFloat(config.khatri_first_discount) || 0;
            const useSecond = config.khatri_enable_second_discount;
            const d2 = useSecond ? (parseFloat(config.khatri_second_discount) || 0) : 0;

            let totalOriginal = 0, totalFinal = 0;
            for (const line of order.lines || []) {
                const orig = (line.price_unit || 0) * (line.qty || 1);
                totalOriginal += orig;
                if (useSecond && d2 > 0) {
                    totalFinal += orig * (1 - d1 / 100) * (1 - d2 / 100);
                } else {
                    totalFinal += orig * (1 - d1 / 100);
                }
            }

            return { d1, d2, useSecond, totalOriginal, totalFinal, totalSaved: totalOriginal - totalFinal };
        } catch(e) {
            console.error("Khatri discount error:", e);
            return null;
        }
    },
});
