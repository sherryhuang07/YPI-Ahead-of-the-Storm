"""Verify credentials provided by the local encrypted-credential launcher.

Never log usernames, passwords, tokens, or authentication exception details.
This checks sign-in only, not permission to download a particular dataset.
"""
import contextlib
import io
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

def main():
    root=Path(__file__).resolve().parents[1]
    if not (os.getenv('EARTHDATA_USERNAME') and os.getenv('EARTHDATA_PASSWORD')):
        print('Please open Connect NASA Earthdata.cmd to sign in on this computer.')
        return 1
    logging.disable(logging.CRITICAL)
    success=False
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            import earthaccess
            auth=earthaccess.login(strategy='environment',persist=False)
            success=bool(auth.authenticated)
    except Exception:
        pass
    folder=root/'data/root-zone/access';folder.mkdir(parents=True,exist_ok=True)
    result=dict(checked_at=datetime.now(timezone.utc).isoformat(),authenticated=success,
                dataset_download_verified=False,
                message='NASA sign-in verified. Dataset access still needs checking.' if success else
                'NASA sign-in did not succeed. Check your credentials, account verification, and network connection.')
    (folder/'earthdata-login-status.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(result['message'])
    return 0 if success else 1

if __name__=='__main__':raise SystemExit(main())
