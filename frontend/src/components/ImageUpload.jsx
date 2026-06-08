import { forwardRef, useImperativeHandle, useRef } from 'react'

const ImageUpload = forwardRef(function ImageUpload({ onImage }, ref) {
  const inputRef = useRef(null)

  useImperativeHandle(ref, () => ({
    triggerOpen: () => inputRef.current?.click()
  }))

  const handleChange = (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    const objectUrl = URL.createObjectURL(file)
    const reader = new FileReader()
    reader.onload = () => {
      const dataUrl = reader.result          // "data:image/jpeg;base64,..."
      const base64 = dataUrl.split(',')[1]
      onImage({
        base64,
        mimeType: file.type,
        preview: dataUrl,      // data URL persists even after objectUrl is revoked
        name: file.name,
        _revokeUrl: objectUrl, // blob URL to free — does NOT affect preview
      })
    }
    reader.onerror = () => URL.revokeObjectURL(objectUrl)
    reader.readAsDataURL(file)
    e.target.value = ''
  }

  return (
    <input
      ref={inputRef}
      type="file"
      accept="image/*"
      className="hidden"
      onChange={handleChange}
    />
  )
})

export default ImageUpload
