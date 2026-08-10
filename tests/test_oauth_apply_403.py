from unittest.mock import patch

from app import oauth


class Response403:
    status_code = 403
    text = "forbidden"

    @staticmethod
    def json():
        return {"errors": [{"type": "forbidden", "value": "vacancy_not_available"}]}


def test_apply_403_does_not_invalidate_valid_oauth_token():
    acc = {"resume_hash": "resume", "cookies": {"hhtoken": "cookie"}}
    with patch.object(oauth, "_obtain_oauth_token", return_value="valid-token"), \
         patch.object(oauth.HH, "post", return_value=Response403()), \
         patch.object(oauth, "invalidate_oauth_token") as invalidate:
        result, info = oauth._oauth_apply(acc, "vacancy")
    assert result == "error"
    assert info["http_status"] == 403
    invalidate.assert_not_called()
