type PhotoVariant = 'profile' | 'assistant' | 'notifications' | 'tender';

const photos: Record<PhotoVariant, { src: string; width: number; height: number }> = {
  profile: { src: '/profile-office.webp', width: 1200, height: 800 },
  assistant: { src: '/assistant-architecture.webp', width: 1400, height: 650 },
  notifications: { src: '/notifications-city.webp', width: 800, height: 1100 },
  tender: { src: '/tender-architecture.webp', width: 1600, height: 650 },
};

export default function PagePhoto({ variant }: { variant: PhotoVariant }) {
  const photo = photos[variant];
  return <figure className={`page-photo page-photo--${variant}`} aria-hidden="true">
    <img src={photo.src} alt="" width={photo.width} height={photo.height} loading="lazy" decoding="async"/>
  </figure>;
}
