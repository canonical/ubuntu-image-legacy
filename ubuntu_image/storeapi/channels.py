from ubuntu_image.storeapi.common import store_api_call


def get_channels(session, package_name):
    """Get current channels config for package through API."""
    channels_endpoint = 'package-channels/%s/' % package_name
    return store_api_call(channels_endpoint, session=session)


def update_channels(session, package_name, data):
    """Update current channels config for package through API."""
    channels_endpoint = 'package-channels/%s/' % package_name
    result = store_api_call(channels_endpoint, method='POST',
                            data=data, session=session)
    if result['success']:
        result['errors'] = result['data']['errors']
        result['data'] = result['data']['channels']
    return result
