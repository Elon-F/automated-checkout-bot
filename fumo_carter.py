import os
from datetime import datetime
from multiprocessing import Manager
from time import sleep
from typing import Tuple, List

import pandas
import requests
from joblib import parallel_backend, Parallel, delayed
from selenium import webdriver
from selenium.webdriver import DesiredCapabilities
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support.ui import WebDriverWait
from selenium_stealth import stealth
from seleniumrequests import Chrome

from fumo_constants import *


class FumoCarter:
    """
    Class reponsible for the entirety of the ordering process.
    """

    def __init__(self, persist_session=RELOAD_SESSION):
        self.driver = get_stealthy_driver(persist_session)
        wait = WebDriverWait(self.driver, 30)
        self.wait_until = wait.until  # a shorthand
        self.order_counter = 0
        self.session = None

        # and we load up the page to setup cookies, sessions, and whatever else. required for the ability to order.
        self.driver.get(USER_INFO_URL)

    def account_login(self):
        """
        Logs into the user account as defined in the constants.
        """
        # Actually, we do need to wait a little...
        self.wait_until(EC.presence_of_element_located((By.CLASS_NAME, 'btn-submit')))

        # First, we have to log in, in order to retrieve the mcode (and avoid changing the ransu). mcodes seem static though
        self.submit_login()
        self.wait_until(EC.presence_of_element_located((By.CLASS_NAME, 'search-box__button')))  # required to ensure the cookies have time to load
        # TODO wait for cookies to appear instead
        print("Account succesfully logged in, probably")
        sleep(1)  # Delay for cookie load?

    def submit_login(self):
        """
        Submits login information on the current page.
        """
        username = self.driver.find_element(by=By.NAME, value='email')
        username.send_keys(USERNAME)
        password = self.driver.find_element(by=By.NAME, value='password')
        password.send_keys(PASSWORD)
        form = self.driver.find_element(by=By.CLASS_NAME, value='btn-submit')
        form.submit()

    def get_session_tokens(self):
        """
        Retrieves relevant session tokens from the cookies, and saves it to the base_request_data imported from the constants.
        """
        # Grab the ransu and mcode into the json baseline data
        # todo move base_request_data internally
        for cookie in self.driver.get_cookies():
            if cookie["name"] == "ransu":
                base_request_data["ransu"] = cookie["value"]
                print(f"Cookie: {cookie}")
            if cookie["name"] == "mcode":
                base_request_data["mcode"] = cookie["value"]
                print(f"Cookie: {cookie}")
        if base_request_data["mcode"] is None:
            print("Error! mcode is None")
        print("")

    def load_cart_page(self):
        """
        Loads the cart webpage.
        """
        self.driver.get(CART_PAGE_URL)
        # XPath for page specific item to identify successful loading of the page.
        self.wait_until(EC.presence_of_element_located((By.XPATH, '//*[@id="__layout"]/div/div[1]/div[2]/div/div/div[1]/section/h2')))

    def define_requests_session(self):
        """
        Creates a `requests` session with the correct paramters to query the API.
        """
        self.session = requests.Session()
        self.session.headers.update(headers)
        for cookie in self.driver.get_cookies():
            self.session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'])

    def wait_for_item_in_stock(self, items_jsons_check_availablity):
        """
        Loop that will wait until either at least one of the items in the list is in stock.
        :return:
        """
        # In this loop, we'll want to, with a high enough interval, check on the fumos to see if they are in stock.
        # Can be done multi-thread, can also be done single thread with lower interval.
        # The moment one is found to be in stock, exit all threads immediately and continue to the next step
        # we set up the async requests session
        # the way this works is by requesting the item data, and checking that the cart_type parameter is equal to CART_TYPE_ON_SALE_PRE, CART_TYPE_ON_SALE_NO_PRE, or CART_TYPE_ON_SALE_BACK?
        run_loop = True
        while run_loop:
            for item in items_jsons_check_availablity:
                sleep(LOOP_WAIT_TIME_MS / 1000)
                response = self.session.request("GET", API_GET_ITEM_INFO_URL, headers=headers, params={**item, "ransu": base_request_data["ransu"]})
                code = response.status_code
                print(f"Response was [{code}]")

                if code == STATUS_SUCCESS:
                    vals = response.json()["item"]

                    if "cart_type" in vals.keys():
                        print(datetime.now().strftime("%H:%M:%S"), end=" - ")
                        print(f"Checked item has cart_type={vals['cart_type']} and is {vals['gname']}")

                        if vals["cart_type"] == CART_TYPE_ON_SALE_PRE:
                            run_loop = False
                            break

                elif code == STATUS_TROTTLED:
                    if WAIT_FOR_ITEMS_STOP_ON_OVERLOAD:
                        print("Throttled.. and out.")
                        run_loop = False
                        break

                    print("Throttled :(\nWaiting for some time. total wait time is expected to be about 55s-1m")
                    sleep(1)

        print("Fumo Detected\n")

    def add_items_to_cart_api_mt(self, items_jsons):
        """
        Attempts to add all the items in the list to the cart. Only items that have been successfully added will be removed from the list.
        This is the multithreaded version
        """
        # First, let's create a variable which can be shared between the threads
        manager = Manager()
        var_flag = manager.list()  # we want to use this to signal that it is time to exit. we use a list, and append to it every fumo which is finished. we exit whenever the flag isn't empty anymore.

        with parallel_backend('threading', n_jobs=10):
            res = Parallel()(delayed(mt_request_wrapper(self.session, var_flag))("POST", API_CART_URL, i, headers=headers, json={**item, "ransu": base_request_data["ransu"], "mcode": base_request_data["mcode"]}) for i, item in enumerate(items_jsons))
        if any(x.status_code != STATUS_SUCCESS for x in res):
            print("Not all fumos passed. what is currently in the cart has been removed from the list, and will be processed after this order goes through.")
            for i, item in enumerate(items_jsons):
                if res[i].status_code == STATUS_SUCCESS:  # if we succeeded, remove from items_jsons
                    for item_data in items_jsons:
                        if item_data['scode'] == item['scode']:
                            print(f"Removed {item['scode']} from item_jsons")
                            items_jsons.remove(item)
                            break
        else:
            print("All fumo successfully added!\n")
        if CART_ONLY_MODE:  # testing flag to block off the checkout process.
            print("You are in cart only mode, script execution stopped.")
            while True:
                sleep(1)

    def add_items_to_cart_api_st(self, items_jsons):
        """
        Singlethreaded, simpler version of add_items_to_cart_api_mt
        """
        for item in items_jsons:
            response = self.driver.request("POST", API_CART_URL, headers=headers, json={**item, "ransu": base_request_data["ransu"], "mcode": base_request_data["mcode"]})
            print(f"Responose for {item} is {response} ")

    def checkout(self):
        """
        Entirely self-contained handling of the checkout process, assumes that the cort does contain items at this point.
        Consists of the checkout flow of the target website.
        """

        def checkout_part_1():
            """
            Handles the first part of the checkout process, "rearrangement options".
            """
            # TODO add checks to verify that we are indeed in the assumed phase
            form = self.driver.find_element(by=By.CLASS_NAME, value='btn-submit')
            form.click()

        def checkout_part_2():
            """
            Handles the second part of the checkout process, "Payment & Shipping".
            """

            def checkout_select_payment_method():
                """
                Selects the correct payment method
                """
                form = self.driver.find_element(by=By.XPATH, value='//*[@id="__layout"]/div/div/div/div/div[2]/section[2]/div/div[2]/div/label')
                form.click()
                # Fill in credit card info
                try:
                    self.driver.find_element(by=By.XPATH, value='//*[@id="__layout"]/div/div/div/div/div[2]/section[2]/div/div[2]/div[2]/div[2]/input').send_keys(CARD_NUMBER)
                    self.driver.find_element(by=By.XPATH, value='//*[@id="__layout"]/div/div/div/div/div[2]/section[2]/div/div[2]/div[2]/div[4]/input').send_keys(CARD_OWNER)
                    self.driver.find_element(by=By.XPATH, value='//*[@id="__layout"]/div/div/div/div/div[2]/section[2]/div/div[2]/div[2]/div[5]/input').send_keys(SECURITY_CODE)
                    self.wait_until(EC.presence_of_element_located((By.XPATH, '//*[@id="selectCardType"]')))
                    Select(self.driver.find_element(by=By.XPATH, value='//*[@id="selectCardType"]')).select_by_index(CARD_TYPE)  # Visa is 0, mastercard is 1
                    Select(self.driver.find_element(by=By.XPATH, value='//*[@id="__layout"]/div/div/div/div/div[2]/section[2]/div/div[2]/div[2]/div[3]/div[1]/select')).select_by_value(EXP_YEAR)  # The year
                    Select(self.driver.find_element(by=By.XPATH, value='//*[@id="__layout"]/div/div/div/div/div[2]/section[2]/div/div[2]/div[2]/div[3]/div[2]/select')).select_by_value(EXP_MONTH)  # The month
                except Exception:  # or don't if it's already in there. There is no other cause for errors besides pre-filled credit card data at this stage, so ignoring it is fine.
                    pass

            def checkout_select_shipping():
                """
                Selects the appropriate shipping method
                """
                if DHL:
                    form = self.driver.find_element(by=By.XPATH, value='//*[@id="__layout"]/div/div/div/div/div[2]/section[3]/div[2]/div[1]/span/label')  # DHL - pain
                else:
                    form = self.driver.find_element(by=By.XPATH, value='//*[@id="__layout"]/div/div/div/div/div[2]/section[3]/div[2]/div[2]/span/label')  # Surface parcel - slow
                form.click()

            checkout_select_shipping()

            # Select payment method and fill relevant information if CC.
            checkout_select_payment_method()

            # Finally, submit the form.
            self.driver.find_element(by=By.CLASS_NAME, value='btn-submit').click()

        # speedy checkout
        self.driver.get(CART_CHECKOUT_URL)
        while True:
            res = self.wait_until_err_handling(by=By.CLASS_NAME, value='btn-submit')  # Wait for the login page to load, or an error to be displayed
            if not res[0]:  # if it returns false, restart the loop
                continue
            self.submit_login()

            # Wait for the "Return" button in the 1st step of the checkout process to show up, indicating the loading of the relevant UI chunk is complete.
            res = self.wait_until_err_handling(by=By.XPATH, value="//button[text()='Return']")
            if not res[0]:  # if it returns false, restart the loop
                continue
            checkout_part_1()

            # we now assume this is the second phase, and move onto the
            # # # CREDIT CARD SECTION # # #
            # but we still check for errors, and in case of errors get booted back to start.
            res = self.wait_until_err_handling(by=By.CLASS_NAME, value="form-radio")  # we wait until the page loads by checking for radio buttons, which are only included in the second part of the checkout iirc
            if not res[0]:  # if it returns false, this means there was an error, so restart the loop
                continue
            checkout_part_2()

            # Then, we wait until there exists a button in the exact right place which indicates phase 3, before finishing up the order.
            res = self.wait_until_err_handling(by=By.XPATH, value='//*[@id="__layout"]/div/div/div/div/div[2]/section/div[3]/form/button')
            if not res[0]:  # if it returns false, this means there was an error, so restart the loop
                continue

            if FINISH_ORDER:
                self.driver.find_element(by=By.CLASS_NAME, value='btn-submit').click()  # Place order!
                sleep(5)  # we need a better wait.
                self.order_counter += 1
                self.driver.save_screenshot(f"proof_of_order_{self.order_counter}.png")
            break

    # Various helper methods and tools. could be extracted.
    def poll_api_for_availability(self):
        """
        Polls the website API and logs the response status to monitor availability and reliability.
        Loops indefinitely.
        """
        results = []
        item = generate_item_jsons_check_info(items_test_data)[0]
        self.define_requests_session()  # define the requests session
        counter = 0
        while True:
            response = self.session.request("GET", API_GET_ITEM_INFO_URL, headers=headers, params={**item, "ransu": base_request_data["ransu"]})
            c_time = datetime.now().strftime("%H:%M:%S")
            code = response.status_code
            print(f"Response at {c_time} was [{code}]")
            if code == STATUS_SUCCESS:
                sleep(LOOP_WAIT_TIME_MS / 1000)
            elif code == STATUS_TOO_MUCH_TRAFFIC:
                print("too much traffic, we try again really fast.")
                sleep(0.1)
            elif code == STATUS_TROTTLED:
                print("Throttled, we try again in a bit.")
                sleep(5)
            results.append({"time": c_time, "response_code": code})
            counter += 1
            if counter % LOG_TO_FILE_FREQUENCY == 0:
                pandas.DataFrame(results, columns=["time", "response_code"]).to_csv("requests_results.csv")

    # returns true if there were no errors and execution can continue normally, false if there was a problem and the loop should restart. also returns the webelem
    # calls wait_until_error with the given params
    def wait_until_err_handling(self, **params) -> Tuple[bool, WebElement]:
        """
        A wrapper around wait_until_error_or_cond(ExpectedCondition), which detects the occurence of errors.
        Appropriately handles the different errors that can occur.
        :return (Boolean to indicate the error status, WebElement being waited on)
        """
        res = self.wait_until_error_or_cond(EC.presence_of_element_located((params["by"], params["value"])))
        retval = True
        if res[0] == ERR_NONE:
            retval = True
        elif res[0] == ERR_CART:  # if cart error, press it and try again
            form = self.driver.find_element(by=By.CLASS_NAME, value='btn-back')
            form.click()  # click the return button, which effectively sends us back to the start, hence
            retval = False
        elif res[0] == ERR_OVERLOAD:  # else. start over.
            self.driver.get(CART_CHECKOUT_URL)
            retval = False
        else:
            pass  # in case of new, more different, exotic errors.
        return retval, res[1]

    def wait_until_error_or_cond(self, condition) -> Tuple[int, WebElement]:  # thanks to https://stackoverflow.com/a/16464305/12362756
        """
        A wrapper around wait_until(ExpectedCondition), which detects the occurence of errors.
        :param condition: an EC condition to wait for
        :return (error code, WebElement being waited on)
        """
        # Wait until either the condition is fullfilled, or an error pops up
        self.wait_until(AnyEc(EC.presence_of_element_located((By.CLASS_NAME, 'alert-area__text')),
                              EC.presence_of_element_located((By.CLASS_NAME, 'item-detail__error-title')),
                              condition))
        elem = None
        try:
            elem = EC.presence_of_element_located((By.CLASS_NAME, 'alert-area__title'))(self.driver)
        except Exception:
            try:
                elem = EC.presence_of_element_located((By.CLASS_NAME, 'item-detail__error-title'))(self.driver)
            except Exception:
                try:
                    elem = condition(self.driver)
                except Exception:  # this should probably do something else.
                    pass
        print(f"found {elem.text}")
        errno = ERR_NONE
        if elem.text == "Access Restriction Notice":
            errno = ERR_OVERLOAD
        elif elem.text == "There was problem.":
            errno = ERR_CART
        return errno, elem


class AnyEc:
    """ Use with WebDriverWait to combine expected_conditions in an OR. """

    def __init__(self, *args):
        self.ecs = args

    def __call__(self, driver):
        for fn in self.ecs:
            try:
                res = fn(driver)
                if res:
                    return True
            except:
                pass


def get_stealthy_driver(persist_session):
    """
    Returns a particularly stealthy webDriver.
    :param persist_session:  Whether to save a persistent session to ./chrome_data
    :return: Stealthified webdriver.
    """
    # Load up the browser
    my_opts = webdriver.ChromeOptions()
    my_opts.add_argument('--disable-blink-features=AutomationControlled')  # stealth-ify?
    if persist_session:
        my_opts.add_argument(f'user-data-dir={os.getcwd()}/chrome_data')

    my_opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    my_opts.add_experimental_option('useAutomationExtension', False)
    my_caps = DesiredCapabilities.CHROME
    my_caps["pageLoadStrategy"] = "none"  # Avoid the automatic waiting on page load.

    driver = Chrome(options=my_opts, desired_capabilities=my_caps)
    stealth(driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
            )
    return driver


# If loop is true, continue sending requests until the item has successfully been added.
# if throttled, we can either ignore the delay, switch to a really short
def mt_request_wrapper(session, exit_flag: List, loop=True):
    """
    Wrapper function for the multithreaded sending of requests.
    :param session: Requests session
    :param exit_flag: Shared list of flags
    :param loop: Whether to keep going after a failure or exit
    :return: result of the last request
    """

    def _internal(method, url, initial_delay, **kargs):
        sleep(initial_delay / 5)
        print(f"Now ordering {kargs['json']['eparams'][1]}")
        while True:
            results = session.request(method, url, **kargs)
            code = results.status_code
            print(f"Status code {code} for ordering of {kargs['json']['eparams'][1]}")
            if code == STATUS_SUCCESS:
                _internal.loop = False
                sleep(WAIT_TIME_AFTER_SUCCESS)
                if not ORDER_ALL_AT_ONCE:  # update the exit flag if we are not ordering all at once, this will make the loop check and act accordingly.
                    exit_flag.append(kargs['json']["scode"])
            elif code == STATUS_UNAVAILABLE or code == STATUS_TOO_MUCH_TRAFFIC:
                sleep(LOOP_WAIT_TIME_MS * 4 / 1000 * len(items_data_fumo))
            elif code == STATUS_TROTTLED:
                sleep(2)
            if len(exit_flag):
                _internal.loop = False
            if not _internal.loop:
                break
            sleep(REQUESTOR_WAIT_MS / 1000)  # this is too short for regular operation, but i guess we assume that we succeed on the first try if not overloaded
        return results

    _internal.loop = loop
    return _internal


def generate_item_jsons_pre_order(base_request_data, items):
    """
    Generates the list of items in the JSON format required for API calls.
    :param base_request_data: the base data for the request, necessary to include the session token.
    :param items JSON formatted data of each item to be ordered.
    :return: List of Json objects based on base_request_data and items
    """
    return [{**base_request_data, 'scode': item['scode'], 'amount': 1 if 'amount' not in item.keys() else min(item['amount'], item['max_cartin_count']),  # Verification step to ensure the requested amount is not above the maximal allowed quantity.
             'eparams': [item['scode'], item['desc'], item['max_cartin_count']]} for item in items]


def generate_item_jsons_check_info(items):
    """
    :param items JSON formatted data of each item.
    :return: List of Json objects containing the basic item information required to retrieve the full item details.
    """
    return [{"lang": "eng", 'gcode': item['scode']} for item in items]


if __name__ == '__main__':

    carter = FumoCarter()

    if SHOULD_AUTOLOGIN:
        carter.account_login()
    else:
        # wait is necessary since without account_login, we jump straight to session_tokens which fails if the page hasn't even loaded once. so we wait for
        sleep(2)

    carter.get_session_tokens()

    # Hijacking this script to place a simple test of the availability of the API from the current location, taking advantage of the logged-in state.
    if TEST_API_AVAILABILITY:
        carter.poll_api_for_availability()

    if TEST_MODE:  # Whether to use the testing item list.
        items_data = items_test_data
    else:
        items_data = items_data_fumo

    item_jsons = generate_item_jsons_pre_order(base_request_data, items_data)
    item_jsons_check_availablity = generate_item_jsons_check_info(items_data)

    # We switch to the cart page, not strictly necessary.
    carter.load_cart_page()
    print("Initial setup: complete")

    # Cautionary sleep.
    sleep(1)

    if WAIT_FOR_USER1:
        input("Press enter to continue to the next step.")

    carter.define_requests_session()

    if WAIT_FOR_ITEMS:  # I recommend not using that live, it's wasting precious time verifying what we already know.
        carter.wait_for_item_in_stock(item_jsons_check_availablity)

    # At this point, we assume all items to be in stock, and try to add them all to cart. Threaded to minimize waiting time.
    while len(item_jsons):  # loop until there are no more left.
        carter.add_items_to_cart_api_mt(item_jsons)
        carter.checkout()
