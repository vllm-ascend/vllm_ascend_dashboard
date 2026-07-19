import vllmAscendLogo from '../assets/vllm-ascend-logo.png'
import './BrandMark.css'

interface BrandMarkProps { className?: string; title?: string }

export default function BrandMark({ className = '', title }: BrandMarkProps) {
  return (
    <img className={`brand-logo-image ${className}`.trim()} src={vllmAscendLogo} alt={title || ''} aria-hidden={title ? undefined : true} />
  )
}
