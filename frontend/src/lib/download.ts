/**
 * Download a file through fetch so the caller knows when it has been delivered
 * (or has failed). A plain anchor/location navigation gives no completion signal.
 *
 * `url` must be relative (no leading slash) so it keeps working behind Home Assistant ingress.
 */

export class DownloadError extends Error {}

function filenameFromDisposition(header: string | null): string | null {
    if (!header) return null
    const star = /filename\*=UTF-8''([^;]+)/i.exec(header)
    if (star) {
        try {
            return decodeURIComponent(star[1].trim())
        } catch {
            // fall through to the plain filename
        }
    }
    const plain = /filename="?([^";]+)"?/i.exec(header)
    return plain ? plain[1].trim() : null
}

async function errorMessage(res: Response): Promise<string> {
    if (res.status === 409) {
        return 'Another export is already running. Wait for it to finish and try again.'
    }
    try {
        const body = (await res.json()) as { detail?: unknown }
        if (typeof body.detail === 'string' && body.detail) return body.detail
    } catch {
        // body was not JSON
    }
    return `Download failed (HTTP ${res.status})`
}

export async function downloadFile(url: string, fallbackName: string): Promise<void> {
    let res: Response
    try {
        res = await fetch(url)
    } catch {
        throw new DownloadError('Could not reach the server. Check the connection and try again.')
    }
    if (!res.ok) throw new DownloadError(await errorMessage(res))

    let blob: Blob
    try {
        blob = await res.blob()
    } catch {
        throw new DownloadError('The download was interrupted. Try again.')
    }

    const name = filenameFromDisposition(res.headers.get('Content-Disposition')) ?? fallbackName
    const objectUrl = URL.createObjectURL(blob)
    try {
        const a = document.createElement('a')
        a.href = objectUrl
        a.download = name
        document.body.appendChild(a)
        a.click()
        a.remove()
    } finally {
        // Revoke on the next tick so the browser has started the save.
        setTimeout(() => URL.revokeObjectURL(objectUrl), 0)
    }
}
