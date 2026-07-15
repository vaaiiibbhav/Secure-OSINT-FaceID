import { Globe } from "lucide-react";
import { GithubIcon, LinkedinIcon } from "../components/icons";

export const developer = {
  name: "Vaibhav Verma",
  role: "Full-Stack Developer — Security & OSINT Tooling",
  initials: "VV",
  links: [
    { label: "GitHub", href: "https://github.com/vaaiiibbhav", icon: GithubIcon },
    { label: "LinkedIn", href: "https://www.linkedin.com/in/vaibhav-verma-905a1b270/", icon: LinkedinIcon },
    { label: "Portfolio", href: "https://vaaiiibbhav.vercel.app/", icon: Globe },
  ],
} as const;
