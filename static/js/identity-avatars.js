// Avatar photos belong to the browser, including uploads from the legacy Prompt editor.
const IDENTITY_AVATAR_MAX_BYTES = 10 * 1024;
const identityAvatarState = {
    user: {image: "", revision: 0, busy: false},
    assistant: {image: "", revision: 0, busy: false},
};

function identityAvatarSnapshot() {
    return Object.fromEntries(Object.entries(identityAvatarState).map(([role, state]) => [role, state.revision]));
}

function renderIdentityAvatar(role) {
    const state = identityAvatarState[role];
    const button = byId("identity-avatar-" + role);
    const image = byId("identity-avatar-" + role + "-image");
    const reset = byId("identity-avatar-" + role + "-reset");
    if (!button || !image || !reset) return;
    button.classList.remove("has-image");
    image.hidden = true;
    reset.hidden = !state.image;
    if (!state.image) { image.removeAttribute("src"); return; }
    const source = state.image;
    image.onload = () => {
        if (state.image !== source) return;
        image.hidden = false;
        button.classList.add("has-image");
    };
    image.onerror = () => {
        image.hidden = true;
        button.classList.remove("has-image");
    };
    image.src = source;
}

function applyIdentityAvatars(data, snapshot) {
    for (const role of Object.keys(identityAvatarState)) {
        const state = identityAvatarState[role];
        if (state.busy || (snapshot && snapshot[role] !== state.revision)) continue;
        state.image = String(data[role + "_avatar"] || "");
        renderIdentityAvatar(role);
    }
}

async function compressIdentityAvatar(file) {
    if (!file || (file.type && !file.type.startsWith("image/"))) throw new Error("请选择一张图片");
    if (file.size > 20 * 1024 * 1024) throw new Error("原图太大，请选择 20MB 以内的图片");
    const url = URL.createObjectURL(file);
    try {
        const image = await new Promise((resolve, reject) => {
            const picture = new Image();
            picture.onload = () => resolve(picture);
            picture.onerror = () => reject(new Error("无法读取图片，请尝试 JPEG、PNG 或 WebP"));
            picture.src = url;
        });
        const side = Math.min(image.naturalWidth, image.naturalHeight);
        if (!side) throw new Error("图片没有可用的尺寸");
        const canvas = document.createElement("canvas");
        const context = canvas.getContext("2d");
        if (!context) throw new Error("当前浏览器暂时无法处理图片");
        const left = (image.naturalWidth - side) / 2;
        const top = (image.naturalHeight - side) / 2;
        for (const size of [256, 192, 160, 128, 96, 64]) {
            canvas.width = canvas.height = size;
            context.fillStyle = "#f4f3ee";
            context.fillRect(0, 0, size, size);
            context.drawImage(image, left, top, side, side, 0, 0, size, size);
            for (const type of ["image/webp", "image/jpeg"]) {
                for (const quality of [.86, .72, .58, .42]) {
                    const blob = await new Promise(resolve => canvas.toBlob(resolve, type, quality));
                    if (!blob || blob.type !== type) break;
                    if (blob.size <= IDENTITY_AVATAR_MAX_BYTES) {
                        const source = await new Promise((resolve, reject) => {
                            const reader = new FileReader();
                            reader.onload = () => resolve(reader.result);
                            reader.onerror = () => reject(new Error("读取压缩图片失败，请重试"));
                            reader.readAsDataURL(blob);
                        });
                        return {source, bytes: blob.size};
                    }
                }
            }
        }
        throw new Error("图片暂时无法压缩到 10KB，请换一张图片");
    } finally { URL.revokeObjectURL(url); }
}

async function updateIdentityAvatar(role, file = null) {
    const state = identityAvatarState[role];
    if (!state || state.busy) return;
    const message = byId("identity-avatar-msg");
    const controls = ["", "-file", "-reset"].map(suffix => byId("identity-avatar-" + role + suffix)).filter(Boolean);
    const button = byId("identity-avatar-" + role);
    state.busy = true;
    ++state.revision;
    controls.forEach(control => { control.disabled = true; });
    button?.setAttribute("aria-busy", "true");
    if (message) message.textContent = file ? "正在准备头像…" : "正在恢复默认头像…";
    try {
        const blob = file ? await window.AshLocal.image(file) : null;
        await window.AshLocal.asset('avatar-' + role, blob);
        if (state.image.startsWith('blob:')) URL.revokeObjectURL(state.image);
        state.image = blob ? URL.createObjectURL(blob) : '';
        renderIdentityAvatar(role);
        if (message) message.textContent = file
            ? "头像已保存在本机"
            : "已恢复默认头像";
    } catch (error) {
        if (message) message.textContent = "头像未更新：" + error.message;
    } finally {
        state.busy = false;
        controls.forEach(control => { control.disabled = false; });
        button?.removeAttribute("aria-busy");
        const input = byId("identity-avatar-" + role + "-file");
        if (input) input.value = "";
    }
}

function initIdentityAvatars() {
    for (const role of Object.keys(identityAvatarState)) {
        const input = byId("identity-avatar-" + role + "-file");
        byId("identity-avatar-" + role)?.addEventListener("click", () => input?.click());
        input?.addEventListener("change", () => {
            if (input.files?.[0]) updateIdentityAvatar(role, input.files[0]);
        });
        byId("identity-avatar-" + role + "-reset")?.addEventListener("click", () => updateIdentityAvatar(role));
    }
}
document.addEventListener("DOMContentLoaded", initIdentityAvatars);
