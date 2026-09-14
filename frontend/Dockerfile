FROM node:22-bookworm-slim AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ENV NEXT_PUBLIC_API_BASE_URL="" NEXT_PUBLIC_DEV_USER_EMAIL=""
RUN npm run build

FROM node:22-bookworm-slim
WORKDIR /app
ENV NODE_ENV=production NEXT_PUBLIC_API_BASE_URL="" NEXT_PUBLIC_DEV_USER_EMAIL=""
COPY --from=build --chown=node:node /app /app
USER node
EXPOSE 3000
CMD ["npm", "run", "start"]
