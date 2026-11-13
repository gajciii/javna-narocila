FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# PostHog project key is public (it ships in the bundle); empty disables analytics.
ARG VITE_POSTHOG_KEY=
ARG VITE_POSTHOG_HOST=https://eu.i.posthog.com
RUN VITE_POSTHOG_KEY=$VITE_POSTHOG_KEY VITE_POSTHOG_HOST=$VITE_POSTHOG_HOST npm run build

FROM nginx:alpine
ARG NGINX_CONFIG=nginx.conf
COPY ${NGINX_CONFIG} /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
