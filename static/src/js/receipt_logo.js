/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { imageUrl } from "@web/core/utils/urls";
import { PosConfig } from "@point_of_sale/app/models/pos_config";

// Receipt logo (res.company.khatri_receipt_logo) if uploaded, else company logo.
// Odoo caches this URL for offline printing (cacheReceiptLogo).
patch(PosConfig.prototype, {
    get receiptCompanyLogoUrl() {
        const company = this.company_id;
        if (company && company.khatri_receipt_logo_key) {
            return imageUrl("res.company", company.id, "khatri_receipt_logo", {
                width: 256,
                height: 256,
                unique: company.khatri_receipt_logo_key,
            });
        }
        return super.receiptCompanyLogoUrl;
    },
});
