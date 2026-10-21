from pathlib import Path
import os


def restrict_access(path: Path, directory: bool = False) -> None:
    if os.name != "nt":
        os.chmod(path, 0o700 if directory else 0o600)
        return
    import win32api
    import win32con
    import win32security
    import ntsecuritycon

    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        acl = win32security.ACL()
        inheritance = win32con.OBJECT_INHERIT_ACE | win32con.CONTAINER_INHERIT_ACE if directory else 0
        acl.AddAccessAllowedAceEx(win32security.ACL_REVISION_DS, inheritance, ntsecuritycon.FILE_ALL_ACCESS, sid)
        win32security.SetNamedSecurityInfo(
            str(path), win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
            None, None, acl, None,
        )
    finally:
        token.Close()
