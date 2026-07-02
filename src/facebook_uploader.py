import os
import requests
import time

try:
    from .logger import logger
except ImportError:
    from logger import logger

def get_fb_credentials():
    access_token = os.environ.get('FB_ACCESS_TOKEN')
    page_id = os.environ.get('FB_PAGE_ID')
    return access_token, page_id

def get_page_access_token(user_token, page_id):
    """
    Queries /me/accounts to find the Page Access Token for the target Page ID.
    If not found or query fails, returns the user_token back as a fallback.
    """
    url = f"https://graph.facebook.com/v19.0/me/accounts?limit=100&access_token={user_token}"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json().get('data', [])
            for page in data:
                if str(page.get('id')) == str(page_id):
                    logger.info(f"Successfully resolved Page Access Token for page: {page.get('name')} ({page_id})")
                    return page.get('access_token')
            logger.warning(f"Target Page ID {page_id} not found in user accounts. Falling back to provided token.")
        else:
            try:
                err_data = response.json()
                err_msg = err_data.get('error', {}).get('message')
                if err_msg:
                    logger.warning(f"Failed to query /me/accounts (status {response.status_code}): {err_msg}. Falling back to provided token.")
                    return user_token
            except Exception:
                pass
            logger.warning(f"Failed to query /me/accounts (status {response.status_code}). Falling back to provided token.")
    except Exception as e:
        logger.error(f"Error resolving Page Access Token: {e}. Falling back to provided token.")
    return user_token

def _handle_api_error(response, step_name):
    """
    Checks the response status. If it's an error, attempts to parse
    the Facebook JSON error details and raises a descriptive Exception.
    """
    if response.status_code >= 400:
        try:
            err_data = response.json()
            error_info = err_data.get('error', {})
            err_msg = error_info.get('message')
            err_code = error_info.get('code', 'unknown')
            err_subcode = error_info.get('error_subcode', 'unknown')
            if err_msg:
                raise Exception(f"Facebook API Error ({step_name}): {err_msg} (code: {err_code}, subcode: {err_subcode})")
        except Exception as e:
            if "Facebook API Error" in str(e):
                raise
        response.raise_for_status()

def refresh_token():
    """
    Refreshes the Facebook Page Access Token by querying /me/accounts.
    Updates the environment variable FB_ACCESS_TOKEN with the resolved Page token.
    """
    user_token, page_id = get_fb_credentials()
    if not user_token or not page_id:
        logger.warning("Cannot refresh token: FB_ACCESS_TOKEN or FB_PAGE_ID missing.")
        return

    page_token = get_page_access_token(user_token, page_id)
    if page_token and page_token != user_token:
        os.environ['FB_ACCESS_TOKEN'] = page_token
        logger.info(f"Facebook token refreshed for Page ID: {page_id}")
    else:
        logger.info("Facebook token is already a Page token or refresh returned same token.")

def upload_reel(video_path, caption, title=None):
    """
    Uploads a video to Facebook Reels using the multi-step Graph API process.
    Returns the Facebook URL if successful, or raises an Exception.
    """
    user_token, page_id = get_fb_credentials()
    if not user_token or not page_id:
        raise Exception("Facebook credentials missing. Ensure FB_ACCESS_TOKEN and FB_PAGE_ID are set.")

    logger.info("Initializing Facebook Graph API upload process...")
    # Resolve Page Access Token
    access_token = get_page_access_token(user_token, page_id)

    file_size = os.path.getsize(video_path)
    
    # Step 1: Initialize Upload
    logger.info("Step 1: Initializing Reel upload session...")
    init_url = f"https://graph.facebook.com/v19.0/{page_id}/video_reels"
    init_payload = {
        'access_token': access_token,
        'upload_phase': 'start',
        'file_size': file_size
    }
    
    init_response = requests.post(init_url, data=init_payload)
    _handle_api_error(init_response, "Initialize Upload")
    init_data = init_response.json()
    
    video_id = init_data.get('video_id')
    upload_url = init_data.get('upload_url')
    
    if not video_id or not upload_url:
        raise Exception("Failed to initialize Facebook upload session.")

    # Step 2: Upload Video Data
    logger.info("Step 2: Uploading video data...")
    headers = {
        'Authorization': f'OAuth {access_token}',
        'offset': '0',
        'file_size': str(file_size)
    }
    
    with open(video_path, 'rb') as f:
        video_data = f.read()
        
    upload_response = requests.post(upload_url, headers=headers, data=video_data)
    _handle_api_error(upload_response, "Upload Video Data")
    
    # Step 3: Publish Video
    logger.info("Step 3: Publishing Reel on Facebook Page...")
    publish_url = f"https://graph.facebook.com/v19.0/{page_id}/video_reels"
    publish_payload = {
        'access_token': access_token,
        'upload_phase': 'finish',
        'video_id': video_id,
        'video_state': 'PUBLISHED',
        'description': caption
    }
    
    publish_response = requests.post(publish_url, data=publish_payload)
    _handle_api_error(publish_response, "Publish Video")
    publish_data = publish_response.json()
    
    if publish_data.get('success'):
        logger.info("Reel published successfully.")
        return f"https://www.facebook.com/{page_id}/videos/{video_id}"
    else:
        raise Exception(f"Failed to publish reel: {publish_data}")

def upload_photo(photo_path, caption):
    """
    Uploads a photo to the Facebook Page using the Graph API.
    Returns the Facebook URL if successful, or raises an Exception.
    """
    user_token, page_id = get_fb_credentials()
    if not user_token or not page_id:
        raise Exception("Facebook credentials missing. Ensure FB_ACCESS_TOKEN and FB_PAGE_ID are set.")

    logger.info("Initializing Facebook Graph API photo upload process...")
    # Resolve Page Access Token
    access_token = get_page_access_token(user_token, page_id)

    upload_url = f"https://graph.facebook.com/v19.0/{page_id}/photos"
    payload = {
        'access_token': access_token,
        'message': caption
    }
    
    with open(photo_path, 'rb') as f:
        files = {
            'source': f
        }
        logger.info("Uploading photo to Facebook Page...")
        response = requests.post(upload_url, data=payload, files=files)
        
    _handle_api_error(response, "Upload Photo")
    data = response.json()
    
    post_id = data.get('post_id') or data.get('id')
    if post_id:
        logger.info("Photo published successfully.")
        if '_' in post_id:
            parts = post_id.split('_')
            return f"https://www.facebook.com/{parts[0]}/posts/{parts[1]}"
        else:
            return f"https://www.facebook.com/{page_id}/posts/{post_id}"
    else:
        raise Exception(f"Failed to publish photo: {data}")
