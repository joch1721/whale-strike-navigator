export default function WhaleIcon({ color = 'currentColor', size = 20, className = '' }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 56"
      className={className}
      xmlns="http://www.w3.org/2000/svg"
    >
      <path
        d="M6 38 C6 20 26 8 48 8 C66 8 80 16 88 27
           C80 25 73 26 68 30
           C63 25 54 23 46 27
           C36 18 20 20 12 34
           C10 35 8 36 6 38 Z"
        fill={color}
      />
      <path d="M4 36 L15 27 L14 42 Z" fill={color} />
      <path d="M4 40 L15 32 L17 46 Z" fill={color} opacity="0.75" />
      <path
        d="M48 26 C52 32 58 36 65 36 C60 30 55 26 48 26 Z"
        fill={color}
        opacity="0.8"
      />
      <circle cx="68" cy="20" r="1.8" fill="#04080f" />
    </svg>
  )
}
