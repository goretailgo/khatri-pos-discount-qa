{
    'name': 'Khatri POS Discount Receipt',
    'version': '19.0.1.0.1',
    'summary': 'Shows 50% + 25% stepped discount breakdown on POS receipt',
    'author': 'Khatri Designer',
    'category': 'Point of Sale',
    'depends': ['point_of_sale', 'l10n_in_pos'],
    'data': [
        'views/pos_config_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'khatri_pos_discount_v2/static/src/js/order_line.js',
            'khatri_pos_discount_v2/static/src/xml/receipt.xml',
            'khatri_pos_discount_v2/static/src/css/receipt.css',
        ],
    },
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
