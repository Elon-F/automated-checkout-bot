import json

import secrets

# # configs
TEST_MODE = True
TEST_API_AVAILABILITY = False  # polls the API and logs the results. the idea is to check how often each VM can get requests through.
CART_ONLY_MODE = False  # Consider the current situation. it might be so slow that only the API Requests to add things to cart will be able to get through.
FINISH_ORDER = not TEST_MODE  # since if we're testing, we don't want to order, and vice versa.
DHL = True
ORDER_ALL_AT_ONCE = False

RELOAD_SESSION = True  # Keep chrome session
SHOULD_AUTOLOGIN = False  # parameter which decides wether or not we need to log in
WAIT_FOR_ITEMS = True  # can be set to false if the orders have already started, which I recommend doing.
WAIT_FOR_ITEMS_STOP_ON_OVERLOAD = True
WAIT_FOR_USER1 = False

# # regular constants

LOOP_WAIT_TIME_MS = 250  # higher wait is necessary for JP.
REQUESTOR_WAIT_MS = 600  # based on whether we expect them to get angry at too many requests, we might want to set to 0 for maximum performance.
WAIT_TIME_AFTER_SUCCESS = 5  # how long to wait after successfully adding a fumo to cart, before force quitting all instances.
USERNAME = secrets.username
PASSWORD = secrets.password

# Card details, all strings except the type:
CARD_OWNER = secrets.card_owner
CARD_TYPE = secrets.card_type  # Visa is 0, mastercard is 1
CARD_NUMBER = secrets.card_number
SECURITY_CODE = secrets.security_code
EXP_YEAR = secrets.expiration_year  # full date
EXP_MONTH = secrets.expiration_month  # no leading 0

CART_TYPE_CLOSED = 2  # pre-orders closed
CART_TYPE_SOON = 5  # available to order soon
CART_TYPE_ON_SALE_PRE = 8  # pre-order

# not currently relevant, but generally good to know
# 3, 4, 6 are all "closed" for various reasons I guess
CART_TYPE_UNAVAILABLE = 1  # unavailable, go figure what this means.
CART_TYPE_ON_SALE_BACK = 7  # back-order
CART_TYPE_ON_SALE_NO_PRE = 9  # not a pre-order, direct buy

STATUS_SUCCESS = 200
STATUS_UNAVAILABLE = 400
STATUS_TROTTLED = 429
STATUS_TOO_MUCH_TRAFFIC = 503

# Errors:
ERR_NONE = 0
ERR_OVERLOAD = 1
ERR_CART = 2

# various
LOG_TO_FILE_FREQUENCY = 25

# URLs
USER_INFO_URL = "https://secure.test.com/"  # User information page, which is expected to automatically prompt if not currently logged in.
CART_PAGE_URL = "https://www.test.com/cart/"
CART_CHECKOUT_URL = "https://secure.test.com/checkoutcart/"
API_GET_ITEM_INFO_URL = "https://api.test.com/api/v1.0/item"
API_CART_URL = "https://api.test.com/api/v1.0/cart"

with open("./fumo_data.json") as fumo_data:
    fumo_data = json.load(fumo_data)["data"]
    headers = fumo_data["headers"]  # The relevant headers for the API requests

    base_request_data = fumo_data["base_request_data"]  # stores the session parameters, used in and required for the API requests

    
    item_json_cart_setup = {  # item added to cart, and then removed. used to pre-generate the current session's cart ID.
        **base_request_data,
        **fumo_data
    }

    # This data is the one we iterate over when looking for an in stock item, and then we order everything in the list
    # max_cartin_count is just the buy limit
    # DESC param is the sname
    items_data_fumo = fumo_data["fumo_items_data"]
    items_test_data = fumo_data["test_items_data"]
