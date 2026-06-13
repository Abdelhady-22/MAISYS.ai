locals {
  azs = ["${var.region}a", "${var.region}b"]

  public_subnet_cidrs  = ["10.0.0.0/24", "10.0.1.0/24"]
  private_subnet_cidrs = ["10.0.10.0/24", "10.0.11.0/24"]

  cluster_name = "maisys-${var.env}"
}

# ──────────────────────────────────────────────────────────────────────────
# VPC
# ──────────────────────────────────────────────────────────────────────────
resource "aws_vpc" "maisys_vpc" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "maisys-net-${var.env}"
  }
}

# ──────────────────────────────────────────────────────────────────────────
# Public subnets — host the NAT gateway and any internet-facing load balancers
# ──────────────────────────────────────────────────────────────────────────
resource "aws_subnet" "public" {
  count = length(local.public_subnet_cidrs)

  vpc_id                  = aws_vpc.maisys_vpc.id
  cidr_block              = local.public_subnet_cidrs[count.index]
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name                                          = "maisys-public-${local.azs[count.index]}-${var.env}"
    "kubernetes.io/role/elb"                      = "1"
    "kubernetes.io/cluster/${local.cluster_name}" = "shared"
  }
}

# ──────────────────────────────────────────────────────────────────────────
# Private subnets — host EKS worker nodes and internal load balancers
# ──────────────────────────────────────────────────────────────────────────
resource "aws_subnet" "private" {
  count = length(local.private_subnet_cidrs)

  vpc_id            = aws_vpc.maisys_vpc.id
  cidr_block        = local.private_subnet_cidrs[count.index]
  availability_zone = local.azs[count.index]

  tags = {
    Name                                          = "maisys-private-${local.azs[count.index]}-${var.env}"
    "kubernetes.io/role/internal-elb"             = "1"
    "kubernetes.io/cluster/${local.cluster_name}" = "shared"
  }
}

# ──────────────────────────────────────────────────────────────────────────
# Internet Gateway — outbound from public subnets
# ──────────────────────────────────────────────────────────────────────────
resource "aws_internet_gateway" "maisys_igw" {
  vpc_id = aws_vpc.maisys_vpc.id

  tags = {
    Name = "maisys-igw-${var.env}"
  }
}

# ──────────────────────────────────────────────────────────────────────────
# NAT Gateway — outbound from private subnets. Single NAT (cost-optimized)
# placed in the first public subnet; both private subnets route through it.
# For higher availability, switch to one NAT per AZ.
# ──────────────────────────────────────────────────────────────────────────
resource "aws_eip" "nat" {
  domain = "vpc"

  tags = {
    Name = "maisys-nat-eip-${var.env}"
  }

  depends_on = [aws_internet_gateway.maisys_igw]
}

resource "aws_nat_gateway" "maisys_nat" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id

  tags = {
    Name = "maisys-nat-${var.env}"
  }

  depends_on = [aws_internet_gateway.maisys_igw]
}

# ──────────────────────────────────────────────────────────────────────────
# Public route table — 0.0.0.0/0 via IGW
# ──────────────────────────────────────────────────────────────────────────
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.maisys_vpc.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.maisys_igw.id
  }

  tags = {
    Name = "maisys-public-rt-${var.env}"
  }
}

resource "aws_route_table_association" "public" {
  count          = length(aws_subnet.public)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# ──────────────────────────────────────────────────────────────────────────
# Private route table — 0.0.0.0/0 via NAT
# ──────────────────────────────────────────────────────────────────────────
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.maisys_vpc.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.maisys_nat.id
  }

  tags = {
    Name = "maisys-private-rt-${var.env}"
  }
}

resource "aws_route_table_association" "private" {
  count          = length(aws_subnet.private)
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}
