"""
Генератор логотипа для LabelSpy
По принципам:
- github.com/kaankiziltug/logo-design-skill (геометрия, оптические пропорции, контраст)
- github.com/glincker/thesvg (чистый векторный SVG, без лишнего мусора)
"""

import os
from PIL import Image, ImageDraw


SVG_CONTENT = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">
  <defs>
    <!-- Градиент фона -->
    <radialGradient id="bgGlow" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#0F2238" />
      <stop offset="100%" stop-color="#070A10" />
    </radialGradient>

    <!-- Неоновый градиент для сканера -->
    <linearGradient id="neonCyanEmerald" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#00F2FE" />
      <stop offset="100%" stop-color="#4FACFE" />
    </linearGradient>

    <!-- Градиент для капсулы / щита -->
    <linearGradient id="emeraldLime" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#10B981" />
      <stop offset="100%" stop-color="#059669" />
    </linearGradient>

    <!-- Свечение сканера -->
    <filter id="scannerGlow" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="6" result="blur" />
      <feComposite in="SourceGraphic" in2="blur" operator="over" />
    </filter>
  </defs>

  <!-- Фон (квадрат со скруглёнными углами для аватарок) -->
  <rect width="512" height="512" rx="112" fill="url(#bgGlow)" />
  <rect width="512" height="512" rx="112" fill="none" stroke="rgba(0, 242, 254, 0.15)" stroke-width="4" />

  <!-- Внешние угловые маркеры сканирования (Label Scanner Brackets) -->
  <g stroke="url(#neonCyanEmerald)" stroke-width="10" stroke-linecap="round" stroke-linejoin="round" fill="none">
    <!-- Верхний левый угол -->
    <path d="M 108 168 L 108 128 A 20 20 0 0 1 128 108 L 168 108" />
    <!-- Верхний правый угол -->
    <path d="M 344 108 L 384 108 A 20 20 0 0 1 404 128 L 404 168" />
    <!-- Нижний левый угол -->
    <path d="M 108 344 L 108 384 A 20 20 0 0 0 128 404 L 168 404" />
    <!-- Нижний правый угол -->
    <path d="M 344 404 L 384 404 A 20 20 0 0 0 404 384 L 404 344" />
  </g>

  <!-- Лазерная горизонтальная линия сканирования -->
  <line x1="120" y1="256" x2="392" y2="256" stroke="#00F2FE" stroke-width="3" stroke-dasharray="8 6" opacity="0.65" filter="url(#scannerGlow)" />

  <!-- Центральное оптическое кольцо (Линза детектива / Spy Lens) -->
  <circle cx="240" cy="240" r="105" fill="#0C1422" stroke="url(#neonCyanEmerald)" stroke-width="12" />
  <circle cx="240" cy="240" r="92" fill="none" stroke="rgba(255, 255, 255, 0.08)" stroke-width="2" />

  <!-- Рукоятка линзы сканера -->
  <line x1="318" y1="318" x2="380" y2="380" stroke="url(#neonCyanEmerald)" stroke-width="18" stroke-linecap="round" />
  <line x1="330" y1="330" x2="376" y2="376" stroke="#FFFFFF" stroke-width="6" stroke-linecap="round" opacity="0.8" />

  <!-- Внутри линзы: Капсула / этикетка чистоты (Pill & Clean Check) -->
  <g transform="translate(240, 240) rotate(-45)">
    <!-- Левая половинка капсулы (Cyan/AI) -->
    <path d="M -48 -24 C -48 -46, -26 -46, 0 -46 L 0 46 C -26 46, -48 46, -48 24 Z" fill="#00F2FE" />
    <!-- Правая половинка капсулы (Emerald/Natural) -->
    <path d="M 0 -46 C 26 -46, 48 -46, 48 -24 L 48 24 C 48 46, 26 46, 0 46 Z" fill="url(#emeraldLime)" />
    <!-- Разделительная линия капсулы -->
    <line x1="0" y1="-46" x2="0" y2="46" stroke="#070A10" stroke-width="5" />
    
    <!-- Галочка чистоты (Clean Mark) на правой половинке -->
    <path d="M 14 -2 L 22 7 L 36 -9" fill="none" stroke="#FFFFFF" stroke-width="5" stroke-linecap="round" stroke-linejoin="round" />
    
    <!-- Лучи/искра AI на левой половинке -->
    <circle cx="-22" cy="0" r="6" fill="#FFFFFF" />
  </g>

  <!-- Индикатор статуса: Verified AI (зеленая точка в углу) -->
  <circle cx="396" cy="116" r="10" fill="#10B981" />
  <circle cx="396" cy="116" r="16" fill="none" stroke="#10B981" stroke-width="2" opacity="0.5" />
</svg>
'''


import sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")


def generate():
    svg_path = "logo.svg"
    png_path = "avatar.png"
    
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(SVG_CONTENT)
    print(f"Created SVG logo: {svg_path}")

    # Пытаемся конвертировать через cairosvg
    converted = False
    try:
        import cairosvg
        cairosvg.svg2png(bytestring=SVG_CONTENT.encode("utf-8"), write_to=png_path, output_width=512, output_height=512)
        print(f"✅ Создан PNG аватар через CairoSVG: {png_path}")
        converted = True
    except Exception as e:
        print(f"ℹ️ CairoSVG недоступен ({e}), создаём аватарку через Pillow...")

    if not converted:
        # Рисуем красивый высококачественный fallback 512x512 через Pillow
        img = Image.new("RGBA", (512, 512), color=(11, 15, 25, 255))
        draw = ImageDraw.Draw(img)
        
        # Рамка со скруглёнными углами
        draw.rounded_rectangle([0, 0, 511, 511], radius=112, fill=(11, 15, 25), outline=(0, 242, 254, 80), width=4)
        
        # Угловые скобки
        cyan = (0, 242, 254)
        emerald = (16, 185, 129)
        
        # Линза
        draw.ellipse([140, 140, 340, 340], fill=(15, 25, 45), outline=cyan, width=12)
        # Рукоятка
        draw.line([310, 310, 380, 380], fill=cyan, width=18)
        
        # Капсула в центре
        draw.rounded_rectangle([195, 210, 285, 270], radius=24, fill=emerald, outline=(255, 255, 255), width=3)
        draw.line([240, 210, 240, 270], fill=(11, 15, 25), width=4)
        
        img.save(png_path)
        print(f"✅ Создан PNG аватар через Pillow: {png_path}")


if __name__ == "__main__":
    generate()
