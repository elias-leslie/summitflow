export const ASSET_TYPES = [
  { value: 'sprite', label: 'Sprite' },
  { value: 'sprite_sheet', label: 'Sprite Sheet' },
  { value: 'portrait', label: 'Portrait' },
  { value: 'environment', label: 'Environment' },
  { value: 'illustration', label: 'Illustration' },
  { value: 'icon', label: 'Icon' },
  { value: 'ui_texture', label: 'UI Texture' },
  { value: 'marketing_mockup', label: 'Marketing Mockup' },
] as const

export const WORKFLOWS = [
  { value: 'concept', label: 'Concept' },
  { value: 'production', label: 'Production' },
  { value: 'marketing', label: 'Marketing' },
  { value: 'ui', label: 'UI' },
] as const

export const BACKGROUND_MODES = [
  { value: 'transparent', label: 'Transparent' },
  { value: 'solid', label: 'Solid' },
  { value: 'scene', label: 'Scene' },
] as const

export const IMAGE_MODELS = [
  {
    id: 'gemini-3-pro-image-preview',
    name: 'Pro Image',
    hint: 'Best quality',
  },
  {
    id: 'gemini-2.5-flash-image',
    name: 'Nano Banana',
    hint: 'Fast',
  },
  {
    id: 'gemini-3.1-flash-image-preview',
    name: 'Nano Banana 2',
    hint: 'Fastest',
  },
] as const

export const SIZES = ['512x512', '1024x1024', '1920x1080'] as const

export const DEFAULT_MOCKUP_TYPE = 'sprite'
export const DEFAULT_SIZE = '1024x1024'
export const DEFAULT_MODEL_ID = IMAGE_MODELS[0].id
