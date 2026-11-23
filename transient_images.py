"""Keep image payloads request-local while retaining readable history markers."""
import json


def without_images(content):
    """Copy message blocks, replacing images without mutating the live request.

    Only traverse message content, never tool arguments or arbitrary JSON data.
    Accept asyncpg's serialized JSON as well as already decoded blocks.
    """
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except (ValueError, TypeError):
            return content
        if isinstance(parsed, list):
            return json.dumps(without_images(parsed), ensure_ascii=False)
        return content
    if not isinstance(content, list):
        return content
    result = []
    for block in content:
        if not isinstance(block, dict):
            result.append(block)
        elif block.get('type') in {'image', 'image_url', 'input_image'}:
            result.append({'type': 'text', 'text': '[图片]'})
        elif block.get('type') == 'tool_result':
            result.append({**block, 'content': without_images(block.get('content'))})
        else:
            result.append(dict(block))
    return result
