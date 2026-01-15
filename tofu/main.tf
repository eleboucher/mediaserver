# =============================================================================
# Bridge Configuration
# =============================================================================

# Import with: tofu import routeros_interface_bridge.br0 bridge1
resource "routeros_interface_bridge" "br0" {
  name           = "bridge1"
  vlan_filtering = true
}


# =============================================================================
# L3 Hardware Offloading (L3HW) Configuration
# =============================================================================

# Run: tofu import routeros_interface_ethernet_switch.switch_global switch1
resource "routeros_interface_ethernet_switch" "switch_global" {
  name             = "switch1"
  l3_hw_offloading = true
}



# =============================================================================
# Bridge Ports - LAN (VLAN 10)
# =============================================================================

resource "routeros_interface_bridge_port" "sfp_wan" {
  bridge    = routeros_interface_bridge.br0.name
  interface = "sfp-sfpplus1"
  pvid      = 10
  comment   = "WAN Uplink"
}

resource "routeros_interface_bridge_port" "kharkiv_mgmt" {
  bridge    = routeros_interface_bridge.br0.name
  interface = "ether1"
  pvid      = 10
  comment   = "Kharkiv Management"
}

resource "routeros_interface_bridge_port" "lehavre_mgmt" {
  bridge    = routeros_interface_bridge.br0.name
  interface = "ether2"
  pvid      = 10
  comment   = "Le-Havre Management"
}

# =============================================================================
# Bridge Ports - Storage (VLAN 20)
# =============================================================================

resource "routeros_interface_bridge_port" "kharkiv_storage" {
  bridge    = routeros_interface_bridge.br0.name
  interface = "ether3"
  pvid      = 20
  comment   = "Kharkiv Storage Link"
}

resource "routeros_interface_bridge_port" "lehavre_storage" {
  bridge    = routeros_interface_bridge.br0.name
  interface = "ether4"
  pvid      = 20
  comment   = "Le-Havre Storage Link"
}

# =============================================================================
# VLAN Table Configuration
# =============================================================================

resource "routeros_interface_bridge_vlan" "vlan10" {
  bridge   = routeros_interface_bridge.br0.name
  vlan_ids = ["10"]
  tagged   = [routeros_interface_bridge.br0.name]
  untagged = ["sfp-sfpplus1", "ether1", "ether2"]
}

resource "routeros_interface_bridge_vlan" "vlan20" {
  bridge   = routeros_interface_bridge.br0.name
  vlan_ids = ["20"]
  untagged = ["ether3", "ether4"]
}

# =============================================================================
# VLAN Interface for Gateway
# =============================================================================

resource "routeros_interface_vlan" "vlan10_interface" {
  interface = routeros_interface_bridge.br0.name
  name      = "vlan10-gateway"
  vlan_id   = 10
}

# =============================================================================
# Ethernet Interface Configuration
# =============================================================================

# LAN Ports - Standard MTU (VLAN 10)
resource "routeros_interface_ethernet" "kharkiv_mgmt_eth" {
  factory_name = "ether1"
  name         = "ether1"
  mtu          = 1500
}

resource "routeros_interface_ethernet" "lehavre_mgmt_eth" {
  factory_name = "ether2"
  name         = "ether2"
  mtu          = 1500
}

# Storage Ports - Jumbo Frames (VLAN 20)
resource "routeros_interface_ethernet" "jumbo_kharkiv" {
  factory_name = "ether3"
  name         = "ether3"
  mtu          = 9000
  l2mtu        = 9216
}

resource "routeros_interface_ethernet" "jumbo_lehavre" {
  factory_name = "ether4"
  name         = "ether4"
  mtu          = 9000
  l2mtu        = 9216
}

# =============================================================================
# IP Configuration
# =============================================================================

resource "routeros_ip_address" "gateway_ip" {
  address   = "192.168.1.2/24"
  interface = routeros_interface_vlan.vlan10_interface.name
  comment   = "LAN Gateway"
}

resource "routeros_ip_route" "default_route" {
  dst_address = "0.0.0.0/0"
  gateway     = "192.168.1.254"
  comment     = "Upstream to Freebox"
}

# =============================================================================
# DHCP Configuration
# =============================================================================

resource "routeros_ip_pool" "lan_pool" {
  name   = "lan-pool"
  ranges = ["192.168.1.100-192.168.1.200"]
}

resource "routeros_ip_dhcp_server_network" "lan_net" {
  address    = "192.168.1.0/24"
  gateway    = "192.168.1.254"
  dns_server = ["1.1.1.1", "1.0.0.1"]
  comment    = "LAN Network"
}

resource "routeros_ip_dhcp_server" "server" {
  name                      = "server1"
  interface                 = routeros_interface_vlan.vlan10_interface.name
  address_pool              = routeros_ip_pool.lan_pool.name
  lease_time                = "1h"
  disabled                  = false
  dynamic_lease_identifiers = "client-mac,client-id"
}

# =============================================================================
# BGP Configuration
# =============================================================================

resource "routeros_routing_bgp_instance" "main" {
  name          = "main"
  as            = "65001"
  routing_table = "main"
}

resource "routeros_routing_bgp_template" "talos" {
  name = "talos-cluster"
  as   = "65001"

  output {
    network = "bgp-networks"
  }
}

resource "routeros_routing_bgp_connection" "kharkiv" {
  name      = "conn-kharkiv"
  as        = "65001"
  instance  = routeros_routing_bgp_instance.main.name
  templates = [routeros_routing_bgp_template.talos.name]

  local {
    role = "ibgp"
  }

  remote {
    address = "192.168.1.41"
    as      = "65002"
  }
}

resource "routeros_routing_bgp_connection" "le_havre" {
  name      = "conn-le-havre"
  as        = "65001"
  instance  = routeros_routing_bgp_instance.main.name
  templates = [routeros_routing_bgp_template.talos.name]

  local {
    role = "ibgp"
  }

  remote {
    address = "192.168.1.7"
    as      = "65002"
  }
}
