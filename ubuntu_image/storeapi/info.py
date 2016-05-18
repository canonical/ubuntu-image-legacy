from ubuntu_image.storeapi.common import store_api_call


def get_info():
    """Return information about the MyApps API.

    Returned data contains information about:
    - version
    - department
    - license
    - country
    - channel
    """
    return store_api_call('')
